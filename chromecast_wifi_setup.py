#!/usr/bin/env python3

import base64
import json
import ssl
import time
from typing import Any, Dict, Optional

import requests
import urllib3

from requests.adapters import HTTPAdapter

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding


CHROMECAST_IP = "192.168.255.249"

SSID = "LVL"
PASSPHRASE = "Welcome1022"

HTTPS_BASE_URL = f"https://{CHROMECAST_IP}:8443"
HTTP_BASE_URL = f"http://{CHROMECAST_IP}:8008"

TIMEOUT = 10


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TLS12Adapter(HTTPAdapter):
    """
    Force TLS 1.2 for Chromecast newer firmware endpoints.
    Equivalent to curl:
      --tlsv1.2 --tls-max 1.2
    """

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def make_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", TLS12Adapter())
    session.headers.update({"User-Agent": "chromecast-wifi-setup-python"})
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs,
) -> Any:
    print(f"{method.upper()} {url}")

    response = session.request(
        method,
        url,
        timeout=TIMEOUT,
        verify=False,
        **kwargs,
    )

    print(f"  HTTP {response.status_code}")

    if response.status_code >= 400:
        raise requests.HTTPError(
            f"{method.upper()} {url} failed with HTTP "
            f"{response.status_code}: {response.text}",
            response=response,
        )

    if response.text:
        try:
            return response.json()
        except json.JSONDecodeError:
            print(response.text)
            return response.text

    return None


def request_json_allow_error(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs,
) -> tuple[bool, Any]:
    """
    Wrapper for endpoints where we want to try a fallback method or URL.
    Returns:
      (True, parsed_response) on success
      (False, exception) on failure
    """

    try:
        result = request_json(session, method, url, **kwargs)
        return True, result
    except requests.RequestException as exc:
        print(f"  Failed: {exc}")
        return False, exc


def find_public_key(data: Any) -> Optional[str]:
    """
    Chromecast firmware variants may put the public key in slightly different places.
    This searches recursively for likely key names.
    """

    likely_names = {
        "public_key",
        "publicKey",
        "public_key_body",
        "rsa_public_key",
        "setup_public_key",
    }

    if isinstance(data, dict):
        for key, value in data.items():
            if key in likely_names and isinstance(value, str):
                return value.strip()

        for value in data.values():
            found = find_public_key(value)
            if found:
                return found

    elif isinstance(data, list):
        for item in data:
            found = find_public_key(item)
            if found:
                return found

    return None


def wrap_rsa_public_key_pem(public_key_body: str) -> bytes:
    return (
        "-----BEGIN RSA PUBLIC KEY-----\n"
        + public_key_body.strip()
        + "\n-----END RSA PUBLIC KEY-----\n"
    ).encode("ascii")


def encrypt_password(public_key_body: str, password: str) -> str:
    pem = wrap_rsa_public_key_pem(public_key_body)

    public_key = serialization.load_pem_public_key(pem)

    encrypted = public_key.encrypt(
        password.encode("utf-8"),
        padding.PKCS1v15(),
    )

    return base64.b64encode(encrypted).decode("ascii")


def extract_networks(scan_results: Any) -> list[Dict[str, Any]]:
    """
    Handles several possible Chromecast scan result shapes.

    Known/possible examples:

      [
        {
          "ssid": "LVL",
          "wpa_auth": 7,
          "wpa_cipher": 4
        }
      ]

      {
        "results": [...]
      }

      {
        "wifi": [...]
      }

      {
        "scan_results": [...]
      }

      {
        "networks": [...]
      }
    """

    if isinstance(scan_results, list):
        return [item for item in scan_results if isinstance(item, dict)]

    if isinstance(scan_results, dict):
        candidates = (
            scan_results.get("results")
            or scan_results.get("wifi")
            or scan_results.get("scan_results")
            or scan_results.get("networks")
            or scan_results.get("ssid_list")
            or []
        )

        if isinstance(candidates, list):
            return [item for item in candidates if isinstance(item, dict)]

    raise RuntimeError(
        f"Unexpected scan_results type: {type(scan_results).__name__}"
    )


def find_ssid(scan_results: Any, ssid: str) -> Dict[str, Any]:
    networks = extract_networks(scan_results)

    for network in networks:
        if network.get("ssid") == ssid:
            return network

    raise RuntimeError(f"Could not find SSID {ssid!r} in scan results.")


def print_scan_summary(scan_results: Any) -> None:
    try:
        networks = extract_networks(scan_results)
    except RuntimeError:
        return

    if not networks:
        print("No Wi-Fi networks found in scan results.")
        return

    print()
    print("Visible SSIDs:")

    for network in networks:
        ssid = network.get("ssid", "<hidden or missing ssid>")
        signal = network.get("signal_level", "unknown")
        wpa_auth = network.get("wpa_auth", "unknown")
        wpa_cipher = network.get("wpa_cipher", "unknown")

        print(
            f"  {ssid} "
            f"(signal={signal}, wpa_auth={wpa_auth}, wpa_cipher={wpa_cipher})"
        )

    print()


def trigger_wifi_scan(session: requests.Session) -> None:
    scan_url = f"{HTTPS_BASE_URL}/setup/scan_wifi"

    print("Triggering Wi-Fi scan...")

    # Newer firmware appears to require POST. Older notes often show GET.
    success, _ = request_json_allow_error(session, "POST", scan_url)

    if success:
        return

    print("POST scan_wifi failed. Trying GET scan_wifi as fallback...")

    success, _ = request_json_allow_error(session, "GET", scan_url)

    if success:
        return

    print()
    print("Could not trigger scan_wifi with POST or GET.")
    print("Continuing anyway. Existing scan results may still be available.")


def get_scan_results(session: requests.Session) -> Any:
    scan_results_url = f"{HTTPS_BASE_URL}/setup/scan_results"
    return request_json(session, "GET", scan_results_url)


def connect_wifi(
    session: requests.Session,
    ssid: str,
    wpa_auth: int,
    wpa_cipher: int,
    enc_passwd: str,
) -> None:
    connect_payload = {
        "ssid": ssid,
        "wpa_auth": wpa_auth,
        "wpa_cipher": wpa_cipher,
        "enc_passwd": enc_passwd,
    }

    connect_url = f"{HTTPS_BASE_URL}/setup/connect_wifi"

    request_json(
        session,
        "POST",
        connect_url,
        headers={"content-type": "application/json"},
        data=json.dumps(connect_payload),
    )

    print("Sent connect_wifi.")


def save_wifi(session: requests.Session) -> bool:
    save_payload = {"keep_hotspot_until_connected": True}

    # Notes for newer firmware are inconsistent here.
    # Try HTTPS 8443 first, then HTTP 8008.
    save_urls = [
        f"{HTTPS_BASE_URL}/setup/save_wifi",
        f"{HTTP_BASE_URL}/setup/save_wifi",
    ]

    for save_url in save_urls:
        success, _ = request_json_allow_error(
            session,
            "POST",
            save_url,
            headers={"content-type": "application/json"},
            data=json.dumps(save_payload),
        )

        if success:
            print(f"Sent save_wifi using {save_url}")
            return True

    return False


def main() -> int:
    session = make_session()

    print("Chromecast Wi-Fi setup script")
    print("Make sure this machine is connected to the Chromecast setup SSID first.")
    print(f"Target Chromecast: {CHROMECAST_IP}")
    print(f"Target Wi-Fi SSID: {SSID}")
    print()

    # 1. Get eureka_info and public key.
    eureka_url = f"{HTTPS_BASE_URL}/setup/eureka_info"
    eureka_info = request_json(session, "GET", eureka_url)

    public_key_body = find_public_key(eureka_info)

    if not public_key_body:
        print()
        print("Could not find the Chromecast RSA public key in /setup/eureka_info.")
        print("Raw response:")
        print(json.dumps(eureka_info, indent=2))
        return 1

    print("Found Chromecast RSA public key.")

    # 2. Trigger Wi-Fi scan.
    trigger_wifi_scan(session)

    print("Waiting for scan results...")
    time.sleep(4)

    # 3. Read Wi-Fi scan results.
    scan_results = get_scan_results(session)
    print_scan_summary(scan_results)

    try:
        network = find_ssid(scan_results, SSID)
    except RuntimeError as exc:
        print()
        print(exc)
        print()
        print("Raw scan results:")
        print(json.dumps(scan_results, indent=2))
        return 1

    wpa_auth = network.get("wpa_auth")
    wpa_cipher = network.get("wpa_cipher")

    if wpa_auth is None or wpa_cipher is None:
        print()
        print(f"Found SSID {SSID!r}, but wpa_auth or wpa_cipher was missing.")
        print("Network entry:")
        print(json.dumps(network, indent=2))
        return 1

    print(f"Found SSID {SSID!r}.")
    print(f"wpa_auth={wpa_auth}, wpa_cipher={wpa_cipher}")

    # 4. Encrypt Wi-Fi password.
    enc_passwd = encrypt_password(public_key_body, PASSPHRASE)
    print("Encrypted Wi-Fi passphrase.")

    # 5. Send connect_wifi.
    connect_wifi(
        session=session,
        ssid=SSID,
        wpa_auth=wpa_auth,
        wpa_cipher=wpa_cipher,
        enc_passwd=enc_passwd,
    )

    # 6. Commit/save Wi-Fi config.
    if not save_wifi(session):
        print()
        print("Failed to send save_wifi on both HTTPS 8443 and HTTP 8008.")
        return 1

    print()
    print("Done. The Chromecast should now attempt to join the Wi-Fi network.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

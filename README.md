# Chromecast Wi-Fi Setup Script

A small Python script to configure a factory-reset Chromecast onto a Wi-Fi network now that google have broken access via the Home app

This script is intended for newer Chromecast firmware that exposes setup endpoints over HTTPS on port `8443`.

Based on the steps documented here.
https://emcot.world/How_To_Connect_a_Gen_1_H2G2_42_Chromecast_Without_Google_Home

## What it does

The script automates the manual Chromecast setup flow:

1. Connects to the Chromecast setup API
2. Reads the Chromecast RSA public key
3. Triggers a Wi-Fi scan
4. Finds the configured SSID
5. Encrypts the Wi-Fi passphrase using the Chromecast public key
6. Sends the Wi-Fi configuration to the Chromecast
7. Saves the Wi-Fi configuration

## Requirements

- Python 3.10 or newer
- A device connected to the Chromecast setup SSID
- Network access to the Chromecast setup address:

```text
192.168.255.249
```

Python packages:

```bash
pip install requests cryptography
```

## Configuration

Edit the variables near the top of the script:

```python
CHROMECAST_IP = "192.168.255.249"

SSID = "SSID_Name"
PASSPHRASE = "Password123"
```

Change `SSID` and `PASSPHRASE` to match the Wi-Fi network the Chromecast should join.

## Usage

Factory reset the Chromecast by holding the button for around 15 seconds, until it starts broadcasting its setup Wi-Fi network.

Connect your laptop or device to the Chromecast setup SSID.

Run the script:

```bash
python chromecast_wifi_setup.py
```

Or make it executable:

```bash
chmod +x chromecast_wifi_setup.py
./chromecast_wifi_setup.py
```

## Expected output

The script should print progress similar to:

```text
Chromecast Wi-Fi setup script
Target Chromecast: 192.168.255.249
Target Wi-Fi SSID: LVL

GET https://192.168.255.249:8443/setup/eureka_info
  HTTP 200
Found Chromecast RSA public key.
Triggering Wi-Fi scan...
POST https://192.168.255.249:8443/setup/scan_wifi
  HTTP 200
Waiting for scan results...
GET https://192.168.255.249:8443/setup/scan_results
  HTTP 200

Visible SSIDs:
  LVL (signal=-40, wpa_auth=7, wpa_cipher=4)

Found SSID 'LVL'.
Encrypted Wi-Fi passphrase.
Sent connect_wifi.
Sent save_wifi using https://192.168.255.249:8443/setup/save_wifi

Done. The Chromecast should now attempt to join the Wi-Fi network.
```

## Troubleshooting

### The Chromecast is not reachable

Make sure your laptop is connected to the Chromecast setup Wi-Fi network.

Test connectivity:

```bash
ping 192.168.255.249
```

### `/setup/scan_wifi` returns HTTP 405

Some firmware versions require `POST` instead of `GET`. The script tries `POST` first, then falls back to `GET`.

### The target SSID is not found

The script prints the visible SSIDs returned by the Chromecast.

Check that:

- The Wi-Fi network is in range
- The SSID is spelled exactly the same
- The Wi-Fi network is broadcasting its SSID
- The Chromecast supports the band/security mode used by the network

### Public key is not found

The script searches the `/setup/eureka_info` response recursively for likely public key fields.

If this fails, manually inspect the response:

```bash
curl -k --tlsv1.2 --tls-max 1.2 \
  "https://192.168.255.249:8443/setup/eureka_info"
```

Then update the script if the public key field name is different.

## Notes

- TLS certificate validation is disabled because the Chromecast setup API uses a local HTTPS endpoint.
- TLS is forced to version 1.2 to match the Chromecast setup endpoint requirements.
- The passphrase is encrypted before being sent to the Chromecast.
- The script is intended for local setup use only.

## Disclaimer

This script is provided as-is. Use it only on devices and networks you own or are authorised to configure.

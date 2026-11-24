# Connect your Arduino to XOT17

This bridge runs on **your computer**. Keep it running while you use the machine. Your machine operator must configure your machine ID and a separate device key on the XOT17 server first. Treat the key like a password; never post it, commit it to Git, or put it in a website.

1. Install Python 3 from https://www.python.org/downloads/. On Windows, select **Add Python to PATH** during installation.
2. Get the project folder from the operator and open Terminal (Mac) or PowerShell (Windows) in that folder. Plug the Arduino in with a USB **data** cable. Close Arduino IDE Serial Monitor and any other bridge using the port.
3. Install the bridge dependency and list ports:

   **Mac**
   ```bash
   python3 -m pip install -r hardware/requirements.txt
   python3 hardware/arduino_bridge.py --list-ports
   ```

   **Windows PowerShell**
   ```powershell
   py -m pip install -r hardware/requirements.txt
   py hardware/arduino_bridge.py --list-ports
   ```

   Note the Arduino port, for example `/dev/cu.usbmodem101` on Mac or `COM3` on Windows. Yours may be different.
4. Ask the operator to send your key using a private, secure channel. Enter it in the terminal without showing it in your command history:

   **Mac**
   ```bash
   read -rs 'HARDWARE_API_KEY?Paste your device key (hidden): '; echo
   export HARDWARE_API_KEY
   ```
   This syntax is for macOS's default zsh. For bash use `read -rs -p 'Paste your device key (hidden): ' HARDWARE_API_KEY; echo` instead.

   **Windows PowerShell**
   ```powershell
   $secret = Read-Host 'Paste your device key' -AsSecureString
   $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
   try { $env:HARDWARE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
   Remove-Variable secret,ptr
   ```
5. Start the bridge, replacing the example port and `RVM-UB-02` if your operator assigned a different ID. The Arduino must use 115200 baud; add `--baud 9600` if its firmware uses 9600 instead.

   **Mac**
   ```bash
   python3 hardware/arduino_bridge.py --url https://xot17.onrender.com --machine RVM-UB-02 --port /dev/cu.usbmodem101
   ```
   **Windows PowerShell**
   ```powershell
   py hardware/arduino_bridge.py --url https://xot17.onrender.com --machine RVM-UB-02 --port COM3
   ```

   Leave this terminal open. Open a **second terminal in the same folder**, repeat step 4 to set the key there, and generate a short-lived, one-use pairing code (this does not open the serial port):

   **Mac**
   ```bash
   python3 hardware/arduino_bridge.py --machine RVM-UB-02 --pair-code
   ```
   **Windows PowerShell**
   ```powershell
   py hardware/arduino_bridge.py --machine RVM-UB-02 --pair-code
   ```
6. Sign in at https://xot17.onrender.com, open **QR Scan**, expand **Have a machine pairing code?**, enter the same machine ID and paste the code. Wait for **Arduino sensor online**, then drop a bottle and check the balance. The code expires after four minutes; the paired session expires after five minutes. Generate a fresh code to pair again.

## Troubleshooting

- **No ports:** use a USB data cable, reconnect the board, and run `--list-ports` again. Check any required board drivers.
- **Wrong port or port busy:** use the exact port from `--list-ports` and close Serial Monitor, browser serial tools, and other bridge processes. Only one program can own the port.
- **Wrong key (401/403):** check the machine ID and ask the operator to check its key. A 503 can also mean that machine is not configured on the server.
- **Server waking up / unreachable:** keep the bridge open and wait. It retries with the same event ID; after 60 seconds it keeps retrying. Pending events are held in memory, so stopping the bridge loses events not yet confirmed. Events that cannot be tied to a confirmed pairing are not credited.
- **No sensor data:** verify the board uses the selected baud rate and the working sensor firmware. Do not upload an older sketch over known working firmware without checking it first.
- **No credit:** make sure the account is signed in, the machine ID matches, and the pairing hasn't expired. The server refuses an event if the pairing changed or expired; it will never transfer that event to a later user. If the bridge reports an uncertain outcome, check account history before trying again.

This ultrasonic prototype detects objects in the chute; it does not prove an item is a PET bottle. Have the operator test one pass at a time and watch for double detections before using it for real rewards.

# MergeX Mail Engine

MergeX is a localized mail merge and automation application built with Python and Flask. It allows users to send highly customized email campaigns directly through the Gmail API, featuring automated follow-ups, real-time data validation, and a persistent system tray integration for background processing.

## Key Features

- **Dynamic Mail Merge**: Automated variable substitution using `{Variable}` syntax from uploaded CSV or Excel files.
- **Automated Follow-up Engine**: Define conditional follow-up messages that trigger automatically if no reply is detected within a set timeframe.
- **Pre-Flight Data Validator**: Scans contact lists for missing information before launching, providing a UI to correct data in real-time.
- **Smart Inbox**: A dedicated dashboard that monitors sent threads for replies and displays message snippets for lead management.
- **Throttling and Rate Limiting**: Intelligent batching with randomized delays to protect sender reputation and comply with Gmail API limits.
- **Campaign Scheduling**: Support for immediate delivery or scheduling campaigns for specific future timestamps.
- **Blacklist Management**: Integrated "Do Not Contact" registry to automatically exclude specific recipients from all future outreach.
- **Analytics Dashboard**: Visual performance tracking including reply rates and follow-up success via Chart.js.
- **System Tray Integration**: Runs as a background service with a persistent icon, ensuring automation continues even when the dashboard is closed.

## Technical Stack

- **Backend**: Python 3.x, Flask
- **Database**: SQLite (Local persistent storage)
- **Email Protocol**: Google Gmail API (OAuth 2.0)
- **Frontend**: Tailwind CSS, Quill.js (Rich Text), Chart.js (Analytics)
- **Data Processing**: Pandas, OpenPyXL
- **Interface**: Pystray (System Tray), Webbrowser (Automatic dashboard launching)

## Installation and Setup

### 1. Prerequisites
- Python 3.8+
- A Google Cloud Project with the Gmail API enabled.
- OAuth 2.0 Desktop Client credentials (downloaded as `credentials.json`).

### 2. Manual Installation
```bash
# Clone the repository
git clone [https://github.com/yourusername/LocalMailApp.git](https://github.com/yourusername/LocalMailApp.git)
cd LocalMailApp

# Install dependencies
pip install Flask pandas google-auth google-auth-oauthlib google-api-python-client openpyxl pystray pillow
```

### 3. Running the Application
Execute the main script to start the background engine and open the dashboard:
```bash
python app.py
```

## Creating a Standalone Executable

To compile the application into a single `.exe` for Windows:
1. Install PyInstaller: `pip install pyinstaller`
2. Run the build command:
```bash
python -m PyInstaller --onefile --noconsole --add-data "templates;templates" app.py
```
The resulting executable will be located in the `dist/` directory.

## Configuration

1. **Credentials**: Upload your `credentials.json` via the **Settings** tab.
2. **Authentication**: Click **Login with Google** to authorize the app. This creates a `token.json` file for persistent session management.
3. **Logout**: The **Logout** button will securely delete both `token.json` and `credentials.json` from the local environment.

## Operational Notes

- **Persistence**: Closing the browser window does not stop the engine. To fully exit the application, right-click the MergeX icon in the system tray and select **Quit**.
- **Local Data**: All campaign history, templates, and settings are stored in `local_data.db`. 
- **System Requirements**: The computer must remain awake for scheduled tasks or follow-ups to execute at their designated times.

```

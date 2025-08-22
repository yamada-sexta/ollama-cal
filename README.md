# Ollama Cal

A simple Python script that creates calendar events on a CalDAV server from natural language. It uses a local [Ollama](https://ollama.com/) instance to parse the text, keeping your data private.

## Features

* **Natural Language Processing**: Describe your event like you would to a person (e.g., "Team meeting every Monday at 10am at the office").
* **Local & Private**: Uses a local Ollama instance, so your event details never leave your machine.
* **Interactive Confirmation**: Shows you the parsed event details and asks for confirmation before creating anything.
* **CalDAV Compatible**: Works with Nextcloud, Baïkal, Radicale, and other CalDAV-compliant calendar servers.

-----

## Setup

1. **Clone the repository:**

    ```bash
    git clone https://github.com/yamada-sexta/ollama-cal.git
    cd ollama-cal
    ```

2. **Create a virtual environment and install dependencies using `uv`:**

    ```bash
    uv venv
    uv sync
    ```

    *This creates a `.venv` folder and installs the packages specified in the project configuration.*

3. **Configure the application:**
    Create a `config.json` file by copying the example below. **Be sure to fill in your own details.**

    ```json
    {
      "ollama": {
        "url": "http://localhost:11434",
        "model": "llama3"
      },
      "caldav": {
        "url": "https://your-caldav-server.com/remote.php/dav/",
        "username": "your-username",
        "password": "your-app-password",
        "calendar_name": "Personal"
      }
    }
    ```

      * **`ollama.model`**: Make sure you have the specified model downloaded (e.g., `ollama pull llama3`).
      * **`caldav.password`**: It's highly recommended to use an app-specific password if your server supports it.
      * **`caldav.calendar_name`**: This must exactly match the display name of your target calendar.

## Usage

1. **Activate the virtual environment:**

    ```bash
    source .venv/bin/activate
    # On Windows, use: .venv\Scripts\activate
    ```

2. **Run the script:**

    ```bash
    python main.py
    ```

3. **Enter your event description:**
    Paste or type the text describing your event. When you're finished, press `Ctrl+D` (Linux/macOS) or `Ctrl+Z` then `Enter` (Windows).

    **Example Input:**

    ```
    Weekly project sync every Friday from 4 PM to 4:30 PM.
    Location is the main conference room.
    Description: Discuss progress on the Q3 roadmap.
    ```

## License

This project is licensed under the **MIT License**.

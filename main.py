import json
import caldav
import requests
import vobject
from datetime import datetime
from uuid import uuid4
from typing import Dict, Any, Optional, List

ConfigDict = Dict[str, Any]

def load_config() -> Optional[ConfigDict]:
    """Loads configuration from config.json."""
    try:
        with open("config.json", "r") as f:
            config: ConfigDict = json.load(f)
            return config
    except FileNotFoundError:
        print("Error: config.json not found.")
        return None
    except json.JSONDecodeError:
        print("Error: Could not decode config.json. Please check its format.")
        return None


def get_event_details_from_llm(
    text: str, ollama_config: ConfigDict
) -> Optional[Dict[str, str]]:
    """
    Sends text to an Ollama server to get structured event details in JSON format.
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # This detailed system prompt guides the LLM to return a well-structured JSON object.
    system_prompt = f"""
    You are an expert assistant that converts natural language text into a structured JSON object
    for a calendar event. The current date and time is {current_time}.
    Analyze the user's text and extract the event details.
    
    The JSON object must have the following structure:
    - "summary": (string) The title or name of the event.
    - "start": (string) The start time in "YYYY-MM-DD HH:MM:SS" format.
    - "end": (string) The end time in "YYYY-MM-DD HH:MM:SS" format. If no duration is specified, assume 1 hour.
    - "location": (string, optional) The event's location.
    - "description": (string, optional) A detailed description of the event.
    - "rrule": (string, optional) A recurrence rule (e.g., "FREQ=WEEKLY;BYDAY=MO" for every Monday).
    
    If a value is not present in the text, omit the key from the JSON object.
    Always respond with ONLY the JSON object and nothing else.
    """

    ollama_api_url = f"{ollama_config['url']}/api/generate"
    payload = {
        "model": ollama_config["model"],
        "system": system_prompt,
        "prompt": text,
        "format": "json",
        "stream": False,
    }

    print(f"Asking {ollama_config['model']} to parse the event...")
    try:
        response = requests.post(ollama_api_url, json=payload)
        response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx)

        response_json = response.json()
        # The actual JSON content is a string inside the 'response' key
        event_data: Dict[str, str] = json.loads(response_json.get("response", "{}"))
        return event_data

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Ollama server at {ollama_api_url}: {e}")
        return None
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from Ollama's response.")
        return None


def create_caldav_event(event_data: Dict[str, str], caldav_config: ConfigDict) -> None:
    """
    Creates a new event on the specified CalDAV server.
    """
    if not all(k in event_data for k in ["summary", "start", "end"]):
        print("Error: LLM response is missing required fields (summary, start, end).")
        return

    # Create an iCalendar object
    cal_event_obj = vobject.iCalendar()  # Renamed 'cal' to avoid confusion
    event = cal_event_obj.add("vevent")

    event.add("summary").value = event_data["summary"]

    # Parse string dates into datetime objects
    try:
        start_dt = datetime.strptime(event_data["start"], "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(event_data["end"], "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        print(f"Error: Could not parse date from LLM response. {e}")
        return

    event.add("dtstart").value = start_dt
    event.add("dtend").value = end_dt
    event.add("dtstamp").value = datetime.now()
    event.add("uid").value = str(uuid4())

    if "location" in event_data:
        event.add("location").value = event_data["location"]
    if "description" in event_data:
        event.add("description").value = event_data["description"]
    if "rrule" in event_data:
        event.add("rrule").value = event_data["rrule"]

    # Connect to CalDAV server
    try:
        client = caldav.DAVClient(
            url=caldav_config["url"],
            username=caldav_config["username"],
            password=caldav_config["password"],
        )
        principal = client.principal()

        # Find the specified calendar
        target_calendar: Optional[caldav.Calendar] = None
        user_calendars: List[caldav.Calendar] = principal.calendars()

        for cal in user_calendars:
            if cal.name == caldav_config.get("calendar_name", ""):
                target_calendar = cal
                break

        if not target_calendar:
            print(f"Error: Calendar '{caldav_config.get('calendar_name')}' not found.")
            print("Available calendars:", [c.name for c in user_calendars])
            return

        # Save the event
        print(f"Creating event in calendar '{target_calendar.name}'...")
        event_result = target_calendar.save_event(ical=cal_event_obj.serialize())
        print("Event created successfully!")
        print(f"Event Summary: {event_result.vobject_instance.vevent.summary.value}")
        print(f"URL: {event_result.url}")

    except Exception as e:
        print(f"An error occurred with the CalDAV server: {e}")


def main() -> None:
    """Main function to run the program."""
    config = load_config()
    if not config:
        return

    print(
        "Please paste the text describing the event and press Ctrl+D (or Ctrl+Z on Windows) when you are done."
    )
    print("-" * 20)
    user_input_lines: List[str] = []
    while True:
        try:
            line = input()
            user_input_lines.append(line)
        except EOFError:
            break

    text = "\n".join(user_input_lines)

    if not text.strip():
        print("No input received. Exiting.")
        return

    # Ensure the config dictionaries exist before passing them
    ollama_conf = config.get("ollama", {})
    caldav_conf = config.get("caldav", {})

    if not ollama_conf or not caldav_conf:
        print("Error: 'ollama' or 'caldav' section missing in config.json")
        return

    event_details = get_event_details_from_llm(text, ollama_conf)

    if not event_details:
        print("\nNo Event Details...")
        return

    
    print("\n--- Parsed Event Details ---")
    print(json.dumps(event_details, indent=2))
    print("--------------------------\n")
    try:
        confirm = input("Does this look correct? (y/n): ").lower().strip()
        if confirm.startswith("y"):
            create_caldav_event(event_details, caldav_conf)
        else:
            print("Event creation cancelled by user.")
    except KeyboardInterrupt:
        print("\nEvent creation cancelled by user.")



if __name__ == "__main__":
    main()

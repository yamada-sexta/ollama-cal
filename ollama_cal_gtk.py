import traceback
import gi
import sys
import json
import caldav
import aiohttp
import vobject
from datetime import datetime
from uuid import uuid4
from typing import Dict, Any, Optional, List, Tuple

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango, Gio

__version__ = "1.0.0"
APP_ID = "com.example.ollamacal"

ConfigDict = Dict[str, Any]

import asyncio
from gi.events import GLibEventLoopPolicy
# Set up the GLib event loop
policy = GLibEventLoopPolicy()
asyncio.set_event_loop_policy(policy)

def load_config() -> Optional[ConfigDict]:
    """Loads configuration from config.json."""
    try:
        with open("config.json", "r") as f:
            config = json.load(f)
            print(f"config loaded:\n{config}")
            return config
    except FileNotFoundError:
        raise Exception("Error: config.json not found.")
    except json.JSONDecodeError:
        raise Exception("Error: Could not decode config.json. Please check its format.")


async def get_event_details_from_llm(text: str, ollama_config: ConfigDict) -> Dict[str, str]:
    """
    Sends text to an Ollama server asynchronously to get structured event details.
    Raises exceptions on failure.
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    print(f"ollama_api_url: {ollama_api_url}, payload:{payload}")

    try:
        # Use aiohttp for asynchronous HTTP requests
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ollama_api_url, json=payload, timeout=30
            ) as response:
                response.raise_for_status()
                response_json = await response.json()
                event_data: Dict[str, str] = json.loads(response_json.get("response", "{}"))

                if not all(k in event_data for k in ["summary", "start", "end"]):
                    raise ValueError(
                        "LLM response is missing required fields (summary, start, end)."
                    )
                return event_data
    except aiohttp.ClientError as e:
        raise ConnectionError(f"Error connecting to Ollama server: {e}")
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Error processing LLM response: {e}")


def _blocking_caldav_create(event_data: Dict[str, str], caldav_config: ConfigDict) -> Tuple[bool, str]:
    """
    Synchronous helper function to create a CalDAV event.
    This will be run in a separate thread by asyncio.to_thread.
    """
    cal_event_obj = vobject.iCalendar()
    event = cal_event_obj.add("vevent")
    event.add("summary").value = event_data["summary"]

    try:
        start_dt = datetime.strptime(event_data["start"], "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(event_data["end"], "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        return False, f"Could not parse date from LLM response: {e}"

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

    try:
        client = caldav.DAVClient(
            url=caldav_config["url"],
            username=caldav_config["username"],
            password=caldav_config["password"],
        )
        principal = client.principal()
        target_calendar = None
        user_calendars = principal.calendars()
        calendar_name = caldav_config.get("calendar_name", "")

        for cal in user_calendars:
            if cal.name == calendar_name:
                target_calendar = cal
                break

        if not target_calendar:
            available = [c.name for c in user_calendars]
            return (
                False,
                f"Calendar '{calendar_name}' not found. Available: {available}",
            )

        target_calendar.save_event(ical=cal_event_obj.serialize())
        return True, f"Event '{event_data['summary']}' created successfully!"

    except Exception as e:
        # Log the full traceback for debugging
        traceback.print_exc()
        return False, f"A CalDAV error occurred: {e}"

async def create_caldav_event_async(
    event_data: Dict[str, str], caldav_config: ConfigDict
) -> Tuple[bool, str]:
    """
    Asynchronously creates a new event on the specified CalDAV server by
    running the synchronous caldav code in a thread pool.
    """
    # asyncio.to_thread is the modern way to run blocking I/O code
    # in an async application without blocking the event loop.
    return await asyncio.to_thread(
        _blocking_caldav_create, event_data, caldav_config
    )


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = load_config()
        self.event_details: Optional[Dict[str, str]] = None

        self.set_default_size(500, 600)
        self.set_title("Ollama Cal")

        # UI Components
        self.header = Gtk.HeaderBar()
        self.window_box = Gtk.Box.new(1, 0)
        self.main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self.toast_overlay = Adw.ToastOverlay()

        self.window_box.append(self.header)

        self.clamp = Adw.Clamp()
        self.clamp.set_child(self.main_box)
        self.window_box.append(self.clamp)

        self.toast_overlay.set_child(self.window_box)
        self.set_content(self.toast_overlay)

        # 1. Input Area
        input_label = Gtk.Label(label="Enter event description:", xalign=0, yalign=0.5)
        input_label.add_css_class("title-4")
        self.main_box.append(input_label)

        scrolled_window = Gtk.ScrolledWindow(vexpand=True)
        self.text_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_tooltip_text(
            "e.g., 'Weekly team meeting every Monday at 10am at the office about the Q3 project review.'"
        )
        scrolled_window.set_child(self.text_view)
        self.main_box.append(scrolled_window)

        # 2. Action Buttons and Spinner
        self.action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.parse_button = Gtk.Button(
            label="Parse Event Details", halign=Gtk.Align.START
        )
        self.parse_button.add_css_class("suggested-action")
        self.parse_button.add_css_class("pill")
        self.parse_button.connect("clicked", self.on_parse_clicked)
        self.spinner = Gtk.Spinner(spinning=False, visible=False)
        self.action_box.append(self.parse_button)
        self.action_box.append(self.spinner)
        self.main_box.append(self.action_box)

        # 3. Results Area (initially hidden)
        self.results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False
        )
        self.main_box.append(self.results_box)

        results_label = Gtk.Label(label="Parsed Event Details", xalign=0)
        results_label.add_css_class("title-4")
        self.results_box.append(results_label)

        self.json_label = Gtk.Label(xalign=0, selectable=True)
        self.json_label.add_css_class("monospace")
        frame = Gtk.Frame()
        frame.set_child(self.json_label)
        self.results_box.append(frame)

        # 4. Confirmation Buttons (initially hidden)
        self.confirm_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.END
        )
        self.clear_button = Gtk.Button(label="Clear")
        self.clear_button.add_css_class("pill")
        self.clear_button.connect("clicked", self.on_clear_clicked)
        self.create_button = Gtk.Button(label="Create Event")
        self.create_button.add_css_class("pill")
        self.create_button.add_css_class("destructive-action")
        self.create_button.connect("clicked", self.on_create_clicked)
        self.confirm_box.append(self.clear_button)
        self.confirm_box.append(self.create_button)
        self.results_box.append(self.confirm_box)

        self.check_config()

    def check_config(self):
        """Loads config and disables UI if it's invalid."""
        try:
            self.config = load_config()
            if "ollama" not in self.config or "caldav" not in self.config:
                raise Exception("'ollama' or 'caldav' section missing in config.json")
        except Exception as e:
            self.show_error_dialog("Configuration Error", str(e))
            self.main_box.set_sensitive(False)

    def show_error_dialog(self, title, message):
        """Displays a modal error dialog."""
        dialog = Adw.MessageDialog(
            heading=title,
            body=message,
            transient_for=self,
            modal=True,
        )
        dialog.add_response("ok", "OK")
        dialog.connect("response", lambda d, r: d.close())
        dialog.present()

    def show_toast(self, message):
        """Displays a short-lived toast message."""
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=4))

    def set_busy(self, busy: bool, is_creating: bool = False):
        """Toggle the UI busy state."""
        self.spinner.set_spinning(busy)
        self.spinner.set_visible(busy)
        self.text_view.set_editable(not busy)

        # If we are creating, keep the parse button disabled
        if is_creating:
            self.parse_button.set_sensitive(not busy)
            self.confirm_box.set_sensitive(not busy)
        else:
            self.parse_button.set_sensitive(not busy)
            if busy:
                self.results_box.set_visible(False)

    def _reset_ui(self):
        """Resets the UI to its initial state."""
        self.event_details = None
        self.text_view.get_buffer().set_text("", -1)
        self.results_box.set_visible(False)
        self.json_label.set_text("")
        self.parse_button.set_sensitive(True)

    # --- Signal Handlers & Async Tasks ---

    def on_clear_clicked(self, button: Gtk.Button):
        self._reset_ui()

    def on_parse_clicked(self, button: Gtk.Button):
        """Synchronous signal handler that schedules the async task."""
        buffer = self.text_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        if not text.strip():
            self.show_toast("Please enter an event description.")
            return
        # Schedule the async method to run on the event loop
        asyncio.create_task(self.do_parse_work(text))

    async def do_parse_work(self, text: str):
        """Asynchronous worker for Ollama API call."""
        self.set_busy(True)
        try:
            result = await get_event_details_from_llm(text, self.config["ollama"])
            self.event_details = result
            formatted_json = json.dumps(self.event_details, indent=2)
            self.json_label.set_markup(
                f"<tt>{GLib.markup_escape_text(formatted_json)}</tt>"
            )
            self.results_box.set_visible(True)
        except Exception as e:
            traceback.print_exc()
            self.show_toast(f"Parsing Failed: {e}")
        finally:
            self.set_busy(False)

    def on_create_clicked(self, button):
        """Synchronous signal handler that schedules the async task."""
        if not self.event_details:
            return
        asyncio.create_task(self.do_create_work())

    async def do_create_work(self):
        """Asynchronous worker for CalDAV event creation."""
        self.set_busy(True, is_creating=True)
        try:
            success, message = await create_caldav_event_async(
                self.event_details, self.config["caldav"]
            )
            if success:
                self.show_toast(message)
                self._reset_ui()
            else:
                self.show_error_dialog("Event Creation Failed", message)
        except Exception as e:
            traceback.print_exc()
            self.show_error_dialog("Event Creation Failed", str(e))
        finally:
            self.set_busy(False, is_creating=True)


class OllamaCalApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(application_id="com.example.ollamacal", **kwargs)
        self.connect("activate", self.on_activate)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit)
        self.add_action(quit_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about)
        self.add_action(about_action)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()

    def on_quit(self, action, param):
        self.quit()

    def on_about(self, action, param):
        """Called when the 'about' action is activated."""
        about = Adw.AboutWindow(
            transient_for=self.win,
            application_name="Ollama Cal",
            application_icon=APP_ID,
            developer_name="Your Name",
            version=__version__,
            comments="Create calendar events from natural language using Ollama and CalDAV.",
            website="https://github.com/your-repo/ollama-cal",
            issue_url="https://github.com/your-repo/ollama-cal/issues",
            license_type=Gtk.License.MIT_X11,
        )
        about.present()


if __name__ == "__main__":
    # PyGObject's GLib main loop integrates with asyncio by default.
    # However, we explicitly get the event loop here to ensure it's created and
    # set on the main thread before the GTK application runs. This allows the
    # GLib main loop to hook into the existing asyncio loop, preventing the
    # "no running event loop" RuntimeError when scheduling async tasks.
    # loop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)
    app = OllamaCalApp()
    sys.exit(app.run(sys.argv))

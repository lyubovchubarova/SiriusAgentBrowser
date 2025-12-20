from collections.abc import Callable
from typing import Any

from playwright.sync_api import FrameLocator, Keyboard, Locator, Mouse


class DebugWrapper:
    def __init__(self, obj: Any, name: str = "page"):
        self._obj = obj
        self._name = name

    def __getattr__(self, name: str) -> Any:
        # Get the attribute from the original object
        attr = getattr(self._obj, name)

        # If it's a method, wrap it
        if callable(attr):
            return self._wrap_method(attr, name)

        # If it's a property that returns an object we want to wrap (like page.keyboard)
        if isinstance(attr, (Keyboard, Mouse)):
            return DebugWrapper(attr, name=f"{self._name}.{name}")

        return attr

    def _wrap_method(
        self, method: Callable[..., Any], method_name: str
    ) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Actions that perform changes or navigation
            action_methods = [
                "goto",
                "click",
                "type",
                "fill",
                "press",
                "check",
                "uncheck",
                "select_option",
                "hover",
                "drag_to",
                "go_back",
                "go_forward",
                "reload",
            ]

            # Methods that return objects we need to wrap
            # locator_methods = ["locator", "frame_locator", "first", "last", "nth"]

            is_action = method_name in action_methods

            if is_action:
                print(f"\n[DEBUG] Playwright Action: {self._name}.{method_name}")
                if args:
                    print(f"  Args: {args}")
                if kwargs:
                    print(f"  Kwargs: {kwargs}")

                while True:
                    user_input = input("  Confirm? [Enter] yes, [s] skip, [q] quit: ")
                    if user_input.lower() == "q":
                        raise KeyboardInterrupt("Debug execution stopped by user.")
                    elif user_input.lower() == "s":
                        print("  Skipped.")
                        return None
                    elif user_input == "":
                        break

            # Execute the actual method
            result = method(*args, **kwargs)

            # If the result is a Locator or FrameLocator, wrap it so we can intercept subsequent calls
            if isinstance(result, (Locator, FrameLocator)):
                # Try to construct a meaningful name
                new_name = f"{self._name}.{method_name}"
                if args:
                    new_name += f"('{args[0]}')"
                return DebugWrapper(result, name=new_name)

            return result

        return wrapper

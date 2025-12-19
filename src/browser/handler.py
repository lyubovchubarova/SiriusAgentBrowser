def handle_command(bc: BrowserController, cmd: dict):
    action = cmd["action"]

    if action == "open":
        bc.open(cmd["url"])

    elif action == "screenshot":
        bc.screenshot_with_bboxes(cmd["path"])

    elif action == "click":
        bc.click_by_id(cmd["id"])

    elif action == "type":
        bc.type_by_id(
            cmd["id"],
            cmd["text"],
            press_enter=cmd.get("press_enter", False)
        )

    elif action == "scroll":
        bc.scroll(cmd["delta_y"])

    elif action == "refresh":
        bc.refresh_bbox_ids()

    elif action == "close":
        bc.close()

    else:
        raise ValueError(f"Unknown action: {action}")

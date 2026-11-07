
  request_physical(reason, scope="app", app=None, action=None)   ask the user up front for
                                    their mouse and keyboard (a step asks by itself):
                                    scope "step", "app", "session"; action "pointer",
                                    "drag", "keyboard", "clipboard"; returns {"granted",
                                    "level", "reason"}

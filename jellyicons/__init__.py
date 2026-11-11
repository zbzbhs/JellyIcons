"""JellyIcons: audio-reactive desktop icon overlay.

Only application-owned windows are created or changed. Desktop icon layout is
read through UI Automation and never written. The single exception is music
mode, which toggles the visibility of the desktop icon ListView -- the same
window the built-in "Show desktop icons" switch toggles -- and always restores
it on exit (plus a detached watchdog for hard kills).
"""

__version__ = "1.8.0"

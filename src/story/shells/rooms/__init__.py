"""The server side of the web version: the lobby and its rooms. Who is in which room, and running each room's game core.

It doesn't know which games exist (the web server hands it the list) or how anything is shown; players reach it only through a Connection."""

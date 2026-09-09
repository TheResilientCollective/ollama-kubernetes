# TODO

- [ ] in containers `/root/.ollama/history` is a text file of all the messages sent to ollama. As long as `/root/.ollama` isn't a volume mount, this will erase when containers reboot. But this history file should still be moved to `/dev/null`

#!/usr/bin/expect -f
#
# Auto-accept Claude Code startup prompts, then hand off to the user.
# Claude Code uses a TUI with ANSI escape codes, so we match loosely
# and send Enter/y for any consent dialogs.

set timeout 10

# Start Claude Code
spawn claude --dangerously-skip-permissions --model sonnet

# Auto-accept up to 10 prompts by sending Enter repeatedly.
# Claude's TUI prompts use highlighted selections — pressing Enter
# accepts the default/highlighted option.
set i 0
while {$i < 10} {
    expect {
        # The Claude prompt character means we're in the session
        -re {❯} {
            break
        }
        -re {> $} {
            break
        }
        # Any prompt asking for confirmation — send Enter
        -re {\?} {
            sleep 0.5
            send "\r"
            incr i
        }
        # Catch-all: if we see any new output, wait a moment then press Enter
        # This handles TUI prompts that don't have clear text markers
        -re {.+} {
            # Don't spam Enter on every output — only after a pause
        }
        timeout {
            # After timeout with no new output, try pressing Enter
            send "\r"
            incr i
        }
    }
}

# Hand control to the user
interact

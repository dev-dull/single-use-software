#!/usr/bin/expect -f
#
# Auto-accept Claude Code startup prompts, then hand off to the user.
# Claude Code uses a TUI with a numbered menu for bypass consent:
#   1. No, exit       (highlighted by default)
#   2. Yes, I accept
# We need to press Down Arrow to select option 2, then Enter.

set timeout 30

spawn claude --dangerously-skip-permissions --model sonnet

# Wait for the bypass consent menu, select "Yes, I accept", then hand off.
set accepted 0
set attempts 0

while {$attempts < 15} {
    expect {
        # Bypass permissions consent — press Down to select "Yes, I accept", then Enter
        "Yes, I accept" {
            sleep 0.3
            # Send Down Arrow (escape sequence) to move to option 2
            send "\x1b\[B"
            sleep 0.3
            send "\r"
            set accepted 1
            incr attempts
        }
        # API key prompt — press Enter to accept default
        "API key" {
            sleep 0.3
            send "\r"
            incr attempts
        }
        # We've reached the Claude prompt — done
        -re {❯} {
            break
        }
        timeout {
            if {$accepted} {
                break
            }
            incr attempts
        }
    }
}

interact

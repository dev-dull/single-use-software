#!/usr/bin/expect -f
#
# Auto-accept Claude Code startup prompts, then hand off to the user.
# This wraps `claude --dangerously-skip-permissions --model sonnet`
# and presses Enter/y for any interactive consent dialogs.

set timeout 30

# Start Claude Code
spawn claude --dangerously-skip-permissions --model sonnet

# Loop: watch for known prompts and auto-accept them.
# Once we see the actual Claude prompt (❯ or >), hand off to the user.
set max_prompts 10
set i 0

while {$i < $max_prompts} {
    expect {
        # API key selection — press Enter to accept default
        -re {Use.*API key|Which.*key|Select.*key|API key} {
            send "\r"
            incr i
        }
        # Bypass mode acceptance — press y then Enter
        -re {bypass|I accept|understand.*risk|dangerous|Do you want to proceed} {
            send "y\r"
            incr i
        }
        # Yes/No prompts — accept
        -re {\(Y/n\)|\(y/N\)|\[Y/n\]|\[y/N\]} {
            send "y\r"
            incr i
        }
        # Press Enter prompts
        -re {Press Enter|press enter|continue} {
            send "\r"
            incr i
        }
        # Claude is ready — we see the prompt character
        -re {❯|> $|^\$ } {
            break
        }
        # Timeout — assume prompts are done
        timeout {
            break
        }
    }
}

# Hand control to the user
interact

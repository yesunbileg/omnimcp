"""Acquire the PTY as controlling terminal after setsid, without threaded preexec_fn."""

import fcntl
import os
import sys
import termios

if __name__ == "__main__":
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.tcsetpgrp(0, os.getpgrp())
    os.execvp(sys.argv[1], sys.argv[1:])

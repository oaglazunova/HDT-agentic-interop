# scripts/pytest_quick.py
import sys, subprocess
sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q"]))

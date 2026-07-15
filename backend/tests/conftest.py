import os
import tempfile

# Point the app at a throwaway data dir BEFORE app.config's settings are read.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="mid-test-"))

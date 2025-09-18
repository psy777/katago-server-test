# katago_api.py

import subprocess
import json
import threading
import queue
import uuid
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Literal

# --- Configuration ---
# Adjust these paths and commands according to your system setup.
# On Mac/Linux, this is likely correct. On Windows, you might need "katago.exe".
KATAGO_EXECUTABLE = "katago"
# Ensure these files are in the same directory as the script, or provide full paths.
KATAGO_CONFIG = "analysis.cfg"
KATAGO_MODEL = "default_model.bin"

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)

class KataGoManager:
    """
    Manages the lifecycle of a single KataGo analysis engine subprocess.
    It starts the engine and communicates with it via stdin/stdout in background threads.
    """
    def __init__(self, command: List[str]):
        self.command = command
        self.process = None
        self.query_queue = queue.Queue()
        self.response_dict = {}
        self.lock = threading.Lock()
        self._stdout_thread = None
        self._stderr_thread = None
        self.is_running = False

    def start_engine(self):
        """Starts the KataGo subprocess and the background threads for communication."""
        if self.is_running:
            logging.warning("KataGo engine is already running.")
            return

        logging.info("Starting KataGo analysis engine...")
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line-buffered
            )
            self.is_running = True
            
            self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
            self._stdout_thread.start()
            self._stderr_thread.start()
            logging.info("KataGo engine started successfully.")
        except FileNotFoundError:
            logging.error(f"FATAL: KataGo executable not found at '{self.command[0]}'. The API cannot start.")
            raise
        except Exception as e:
            logging.error(f"FATAL: Failed to start KataGo engine: {e}")
            raise


    def stop_engine(self):
        """Stops the KataGo engine gracefully."""
        if not self.is_running or not self.process:
            return
        logging.info("Stopping KataGo engine...")
        self.is_running = False
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        
        if self._stdout_thread: self._stdout_thread.join(timeout=2)
        if self._stderr_thread: self._stderr_thread.join(timeout=2)
        logging.info("KataGo engine stopped.")

    def _read_stdout(self):
        """Continuously reads from KataGo's stdout and sorts responses by ID."""
        while self.is_running and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                response = json.loads(line)
                # Check for an error field in the response from KataGo
                if "error" in response:
                    query_id = response.get("id")
                    logging.error(f"KataGo returned an error for query {query_id}: {response['error']}")
                    # Store the error response so the waiting thread can see it
                    if query_id:
                        self.response_dict[query_id] = response
                    continue

                query_id = response.get("id")
                if query_id:
                    self.response_dict[query_id] = response
            except (json.JSONDecodeError, BrokenPipeError):
                continue

    def _read_stderr(self):
        """Continuously logs KataGo's stderr output."""
        while self.is_running and self.process.stderr:
            try:
                line = self.process.stderr.readline()
                if not line:
                    break
                logging.warning(f"[KataGo STDERR] {line.strip()}")
            except BrokenPipeError:
                continue

    def query_analysis(self, request_data: dict, timeout: int = 180) -> dict:
        """Sends a query to KataGo and waits for the final response."""
        if not self.is_running:
            raise RuntimeError("KataGo engine is not running.")

        query_id = str(uuid.uuid4())
        request_data["id"] = query_id
        
        with self.lock:
            try:
                self.process.stdin.write(json.dumps(request_data) + "\n")
                self.process.stdin.flush()
            except BrokenPipeError:
                logging.error("Failed to write to KataGo stdin. The process may have crashed.")
                # Attempt a restart or handle gracefully
                self.stop_engine()
                self.start_engine()
                raise HTTPException(status_code=503, detail="KataGo engine crashed and is restarting. Please try again.")

        # Wait for the final response
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            if query_id in self.response_dict:
                response = self.response_dict[query_id]
                # If KataGo sent back an error, raise it immediately
                if "error" in response:
                    del self.response_dict[query_id]
                    raise HTTPException(status_code=400, detail=f"KataGo Error: {response['error']}")

                # The final analysis response has isDuringSearch=false
                if not response.get("isDuringSearch", True):
                    del self.response_dict[query_id]
                    return response
            time.sleep(0.01) # Small sleep to prevent busy-waiting

        # If we exit the loop, it's a timeout
        if query_id in self.response_dict:
            del self.response_dict[query_id]
        raise HTTPException(status_code=504, detail=f"KataGo analysis timed out after {timeout} seconds.")


# --- Pydantic Models for API Data Validation ---

class KataGoQuery(BaseModel):
    """Defines the structure of a valid analysis request body."""
    initialStones: List[Tuple[Literal["B", "W"], str]] = Field(default=[], description="List of initial black and white stones, e.g., [['B', 'Q4'], ['W', 'D16']]")
    moves: List[Tuple[Literal["B", "W"], str]] = Field(default=[], description="List of moves played in sequence.")
    boardXSize: int = Field(default=19, gt=1, lt=26)
    boardYSize: int = Field(default=19, gt=1, lt=26)
    komi: float = Field(default=6.5)
    rules: str = Field(default="japanese")
    # ** THE FIX: Changed Literal to accept lowercase 'b' and 'w' as required by KataGo **
    initialPlayer: Optional[Literal["b", "w"]] = Field(default=None, description="Player to move first ('b' or 'w'). Crucial if initialStones is used.")
    maxVisits: Optional[int] = Field(default=None, gt=0, description="Maximum analysis visits for KataGo.")
    analyzeTurns: List[int] = Field(default=[0], description="Which turn numbers to analyze.")

# --- FastAPI Application ---

# Build the command to start KataGo
katago_command = [KATAGO_EXECUTABLE, "analysis", "-config", KATAGO_CONFIG, "-model", KATAGO_MODEL]
# Instantiate the manager
katago_manager = KataGoManager(command=katago_command)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the startup and shutdown of the KataGo engine."""
    katago_manager.start_engine()
    yield
    katago_manager.stop_engine()

# Create the FastAPI app instance with the lifespan manager
app = FastAPI(
    title="KataGo Analysis API",
    description="A web server to interact with a KataGo analysis engine.",
    lifespan=lifespan
)

@app.post("/analyze", summary="Request a Go position analysis")
async def analyze_position(query: KataGoQuery):
    """
    Accepts a Go board position and returns KataGo's analysis.

    This endpoint forwards the request to a running KataGo engine.
    The query must conform to the KataGo analysis query format.
    """
    if not katago_manager.is_running:
        raise HTTPException(status_code=503, detail="KataGo engine is not available.")
    
    try:
        # The Pydantic model is automatically converted to a dict
        analysis_result = katago_manager.query_analysis(query.model_dump(exclude_none=True))
        return analysis_result
    except HTTPException as e:
        # Re-raise HTTP exceptions (like timeouts or KataGo errors)
        raise e
    except Exception as e:
        logging.error(f"An unexpected error occurred during analysis: {e}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

@app.get("/", summary="Check API status")
def root():
    """Returns the status of the API and the KataGo engine."""
    return {
        "status": "online",
        "katago_engine_running": katago_manager.is_running
    }

# To run this server:
# 1. Install necessary packages: pip install fastapi "uvicorn[standard]"
# 2. Save the code as katago_api.py
# 3. Run from your terminal: uvicorn katago_api:app --host 0.0.0.0 --port 8000

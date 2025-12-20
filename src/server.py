import logging
import os
import queue
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.orchestrator import Orchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Server")


# ... imports ...


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Any:
    # Startup
    worker.start()
    # We don't wait for full readiness here to avoid blocking server startup if extension is closed.
    # The worker will block on extension check, which is fine.
    yield
    # Shutdown (optional: stop worker)
    worker.request_queue.put(None)
    worker.join(timeout=5)


app = FastAPI(title="Sirius Agent Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Worker Thread Infrastructure ---
# We use a dedicated thread for the Orchestrator because Playwright Sync API
# must run in a single thread and cannot be mixed with asyncio loops easily.


class AgentWorker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.request_queue: queue.Queue[Any] = queue.Queue()
        self.orchestrator: Orchestrator | None = None
        self.ready_event = threading.Event()
        self.init_error: Exception | None = None

    def run(self) -> None:
        """Main loop of the worker thread."""
        try:
            self._initialize()
            self.ready_event.set()
        except Exception as e:
            logger.error(f"Worker initialization failed: {e}")
            self.init_error = e
            self.ready_event.set()
            return

        logger.info("Worker thread started and ready.")

        while True:
            item = self.request_queue.get()
            if item is None:
                break  # Stop signal

            query, result_queue = item
            try:
                logger.info(f"Worker processing query: {query}")
                if self.orchestrator:
                    result = self.orchestrator.process_request(query)
                    result_queue.put({"status": "success", "result": result})
                else:
                    result_queue.put(
                        {"status": "error", "message": "Orchestrator not initialized"}
                    )
            except Exception as e:
                logger.error(f"Worker error: {e}")
                result_queue.put({"status": "error", "message": str(e)})
            finally:
                self.request_queue.task_done()

    def _initialize(self) -> None:
        load_dotenv()
        provider = os.getenv("LLM_PROVIDER", "yandex")
        model = os.getenv("LLM_MODEL", "gpt-4o")
        cdp_url = os.getenv("CDP_URL", "http://127.0.0.1:9222")

        logger.info("Initializing Orchestrator in worker thread...")

        # Retry logic for browser connection
        max_retries = 5
        for i in range(max_retries):
            try:
                self.orchestrator = Orchestrator(
                    headless=False,
                    debug_mode=False,
                    llm_provider=provider,
                    llm_model=model,
                    cdp_url=cdp_url,
                )
                self.orchestrator.start_browser()
                break
            except Exception as e:
                if i == max_retries - 1:
                    raise e
                logger.warning(
                    f"Connection attempt {i+1} failed: {e}. Retrying in 2s..."
                )
                time.sleep(2)

        # Extension polling
        logger.info("Waiting for 'Sirius Agent Browser' extension...")
        while True:
            if (
                self.orchestrator
                and self.orchestrator.browser_controller.is_extension_installed(
                    "Sirius Agent Browser"
                )
            ):
                logger.info("✅ Extension 'Sirius Agent Browser' detected.")
                break

            # Allow stopping initialization
            if self.orchestrator and self.orchestrator._stop_requested:
                logger.info("Initialization interrupted by user stop request.")
                break

            logger.info("Waiting for extension... (Open Side Panel to wake it up)")
            time.sleep(2)

    def process_query(self, query: str) -> dict[str, Any]:
        if self.init_error:
            raise self.init_error

        result_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.request_queue.put((query, result_queue))
        return result_queue.get()

    def stop_current_task(self) -> None:
        if self.orchestrator:
            self.orchestrator.stop()


# Global worker instance
worker = AgentWorker()


class ChatRequest(BaseModel):
    query: str


# Allow CORS for Chrome Extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/stop")  # type: ignore[untyped-decorator]
async def stop_endpoint() -> dict[str, str]:
    if not worker.is_alive():
        raise HTTPException(status_code=500, detail="Agent worker thread is dead")

    worker.stop_current_task()
    return {"status": "success", "message": "Stop signal sent"}


@app.post("/chat")  # type: ignore[untyped-decorator]
async def chat_endpoint(request: ChatRequest) -> dict[str, Any]:
    if worker.init_error:
        raise HTTPException(
            status_code=500, detail=f"Agent initialization failed: {worker.init_error}"
        )

    if not worker.is_alive():
        raise HTTPException(status_code=500, detail="Agent worker thread is dead")

    # Offload the waiting to a thread pool so we don't block the async event loop
    # while waiting for the worker thread queue
    from fastapi.concurrency import run_in_threadpool

    response = await run_in_threadpool(worker.process_query, request.query)
    return cast("dict[str, Any]", response)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)

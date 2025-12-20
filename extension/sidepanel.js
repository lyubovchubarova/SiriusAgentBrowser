document.addEventListener("DOMContentLoaded", () => {
	const chatContainer = document.getElementById("chat-container");
	const promptInput = document.getElementById("prompt-input");
	const sendBtn = document.getElementById("send-btn");
	const stopBtn = document.getElementById("stop-btn");

	// Configuration
	const API_URL = "http://127.0.0.1:8000/chat";
	const STOP_URL = "http://127.0.0.1:8000/stop";

	function addMessage(text, type) {
		const div = document.createElement("div");
		div.className = `message ${type}-message`;
		div.textContent = text;
		chatContainer.appendChild(div);
		chatContainer.scrollTop = chatContainer.scrollHeight;
	}

	function addStatus(text) {
		const div = document.createElement("div");
		div.className = "status-message";
		div.textContent = text;
		div.id = "current-status";

		// Remove previous status if exists
		const prev = document.getElementById("current-status");
		if (prev) prev.remove();

		chatContainer.appendChild(div);
		chatContainer.scrollTop = chatContainer.scrollHeight;
	}

	async function sendMessage() {
		const text = promptInput.value.trim();
		if (!text) return;

		// UI Updates
		addMessage(text, "user");
		promptInput.value = "";
		promptInput.disabled = true;
		sendBtn.disabled = true;
		sendBtn.style.display = "none";
		stopBtn.style.display = "flex";
		addStatus("Агент думает...");

		try {
			const response = await fetch(API_URL, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({ query: text }),
			});

			const data = await response.json();

			// Remove status
			const status = document.getElementById("current-status");
			if (status) status.remove();

			if (data.status === "success") {
				addMessage(data.result, "agent");
			} else {
				addMessage(`Ошибка: ${data.message}`, "agent");
			}
		} catch (error) {
			const status = document.getElementById("current-status");
			if (status) status.remove();
			addMessage(
				"Ошибка соединения с сервером агента. Убедитесь, что python-сервер запущен.",
				"agent"
			);
			console.error(error);
		} finally {
			promptInput.disabled = false;
			sendBtn.disabled = false;
			sendBtn.style.display = "flex";
			stopBtn.style.display = "none";
			promptInput.focus();
		}
	}

	async function stopExecution() {
		try {
			await fetch(STOP_URL, { method: "POST" });
			addStatus("Отправлен сигнал остановки...");
		} catch (error) {
			console.error("Failed to stop:", error);
		}
	}

	sendBtn.addEventListener("click", sendMessage);
	stopBtn.addEventListener("click", stopExecution);

	promptInput.addEventListener("keypress", (e) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	});
});

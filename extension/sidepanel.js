document.addEventListener("DOMContentLoaded", () => {
	const themeToggle = document.getElementById("theme-toggle");

	// загрузка сохранённой темы
	const savedTheme = localStorage.getItem("theme");
	if (savedTheme === "dark") {
		document.body.classList.add("dark");
		themeToggle.textContent = "☀️";
	} else {
		themeToggle.textContent = "🌙";
	}

	// переключатель
	themeToggle.addEventListener("click", () => {
		document.body.classList.toggle("dark");
		const isDark = document.body.classList.contains("dark");

		localStorage.setItem("theme", isDark ? "dark" : "light");
		themeToggle.textContent = isDark ? "☀️" : "🌙";
	});

	const chatContainer = document.getElementById("chat-container");
	const promptInput = document.getElementById("prompt-input");
	const sendBtn = document.getElementById("send-btn");
	const stopBtn = document.getElementById("stop-btn");

	// Configuration
	const API_URL = "http://127.0.0.1:8000/chat";
	const STREAM_URL = "http://127.0.0.1:8000/stream";
	const STOP_URL = "http://127.0.0.1:8000/stop";
	const HEALTH_URL = "http://127.0.0.1:8000/health";

	let currentThinkingDiv = null;
	let isConnected = false;
	let evtSource = null;

	// Initial state
	sendBtn.disabled = true;
	promptInput.disabled = true;
	promptInput.placeholder = "Connecting to server...";

	function checkHealth() {
		fetch(HEALTH_URL)
			.then((res) => res.json())
			.then((data) => {
				if (data.status === "ok") {
					if (!isConnected) {
						isConnected = true;
						sendBtn.disabled = false;
						promptInput.disabled = false;
						promptInput.placeholder = "Type a message...";
						addStatus("Connected to agent server.");
						// Start stream listener only when connected
						initEventSource();
					}
				}
			})
			.catch(() => {
				if (isConnected) {
					isConnected = false;
					sendBtn.disabled = true;
					promptInput.disabled = true;
					promptInput.placeholder = "Reconnecting...";
					addStatus("Connection lost. Retrying...");
					if (evtSource) {
						evtSource.close();
						evtSource = null;
					}
				}
			});
	}

	// Poll health every 1s
	setInterval(checkHealth, 1000);
	checkHealth(); // Check immediately

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

	function getOrCreateThinkingDiv() {
		if (!currentThinkingDiv) {
			// Create container
			const container = document.createElement("div");
			container.className = "thinking-container";

			// Create header
			const header = document.createElement("div");
			header.className = "thinking-header";
			header.innerHTML =
				'<span>Thinking Process</span><span class="toggle-icon">▼</span>';

			// Create content
			const content = document.createElement("div");
			content.className = "thinking-content";

			// Toggle logic
			header.addEventListener("click", () => {
				content.classList.toggle("collapsed");
				const icon = header.querySelector(".toggle-icon");
				icon.style.transform = content.classList.contains("collapsed")
					? "rotate(-90deg)"
					: "rotate(0deg)";
			});

			container.appendChild(header);
			container.appendChild(content);
			chatContainer.appendChild(container);
			chatContainer.scrollTop = chatContainer.scrollHeight;

			// Store the content div as the target for streaming
			currentThinkingDiv = content;
		}
		return currentThinkingDiv;
	}

	function initEventSource() {
		if (evtSource) {
			evtSource.close();
		}
		console.log("Connecting to EventSource at", STREAM_URL);
		evtSource = new EventSource(STREAM_URL);

		evtSource.onmessage = (event) => {
			// console.log("Stream event:", event.data);
			if (event.data === ": keepalive") return;

			try {
				const data = JSON.parse(event.data);

				if (data.type === "token") {
					const div = getOrCreateThinkingDiv();
					div.textContent += data.content;
					chatContainer.scrollTop = chatContainer.scrollHeight;
				} else if (data.type === "status") {
					addStatus(data.content);
				}
			} catch (e) {
				console.error("Error parsing stream event:", e);
			}
		};

		evtSource.onerror = (err) => {
			console.error("EventSource failed:", err);
			// EventSource automatically tries to reconnect
		};
	}

	// Start listening to the stream
	// initEventSource(); // Moved to checkHealth

	async function sendMessage() {
		const text = promptInput.value.trim();
		if (!text) return;

		// Reset thinking div for the new request
		currentThinkingDiv = null;

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
				const errorMsg = data.message || data.detail || "Unknown error";
				addMessage(`Ошибка: ${errorMsg}`, "agent");
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

			// Reset thinking div again to ensure next tokens (if any delayed) don't append to old one
			currentThinkingDiv = null;
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

	const micBtn = document.getElementById("mic-btn");
    let recognition = null;

    // Проверяем поддержку API
    if ('webkitSpeechRecognition' in window) {
        recognition = new webkitSpeechRecognition();
        recognition.continuous = false; // Остановить запись после одной фразы
        recognition.interimResults = true; // Показывать текст в процессе говорения
        recognition.lang = 'ru-RU'; // Установите нужный язык

        recognition.onstart = () => {
            micBtn.classList.add("listening");
            promptInput.placeholder = "Говорите...";
        };

        recognition.onend = () => {
            micBtn.classList.remove("listening");
            promptInput.placeholder = isConnected ? "Введите задачу..." : "Connecting...";
            promptInput.focus();
        };

		recognition.onresult = (event) => {
            let finalTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                }
            }

            if (finalTranscript) {
                const currentText = promptInput.value;
                const prefix = (currentText && !currentText.endsWith(' ')) ? ' ' : '';
                
                // 1. Добавляем распознанный текст в инпут
                promptInput.value = currentText + prefix + finalTranscript;

                // 2. Останавливаем распознавание (чтобы не слушало лишнего)
                recognition.stop();

                // 3. АВТОМАТИЧЕСКАЯ ОТПРАВКА
                // Делаем небольшую задержку (300мс), чтобы пользователь увидел текст перед отправкой
                setTimeout(() => {
                    sendMessage();
                }, 300);
            }
        };

        recognition.onerror = (event) => {
            console.error("Speech recognition error", event.error);
            micBtn.classList.remove("listening");
            
            // КЛЮЧЕВОЙ МОМЕНТ: Обработка отсутствия прав
            if (event.error === 'not-allowed' || event.error === 'permission-denied') {
                addStatus("Требуется разрешение на микрофон.");
                // Открываем страницу разрешения в новой вкладке
                chrome.tabs.create({ url: 'permission.html' });
            }
        };
	} else {
		micBtn.style.display = 'none'; // Скрыть кнопку, если браузер не поддерживает
		console.warn("Web Speech API not supported");
	}

    micBtn.addEventListener("click", () => {
        if (!recognition) return;

        if (micBtn.classList.contains("listening")) {
            recognition.stop();
        } else {
            // Если соединение еще не установлено, не даем говорить (опционально)
            if (!isConnected) {
                addStatus("Дождитесь соединения с сервером.");
                return;
            }
            try {
                recognition.start();
            } catch (e) {
                console.error(e);
            }
        }
    });
});

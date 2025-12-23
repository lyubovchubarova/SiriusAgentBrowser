document.addEventListener("DOMContentLoaded", () => {
// --- ЭЛЕМЕНТЫ UI ---
const chatContainer = document.getElementById("chat-container");
const promptInput = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");
const stopBtn = document.getElementById("stop-btn");
const micBtn = document.getElementById("mic-btn");

// Темы
const themeMenuBtn = document.getElementById("theme-menu-btn");
const themeOptions = document.getElementById("theme-options");
const themeBtns = document.querySelectorAll(".theme-opt");

// Звук
const muteBtn = document.getElementById("mute-toggle");

// --- КОНФИГУРАЦИЯ API ---
const API_URL = "http://127.0.0.1:8000/chat";
const STREAM_URL = "http://127.0.0.1:8000/stream";
const STOP_URL = "http://127.0.0.1:8000/stop";
const HEALTH_URL = "http://127.0.0.1:8000/health";
const ANSWER_URL = "http://127.0.0.1:8000/answer";

// --- СОСТОЯНИЕ ---
let currentThinkingDiv = null;
let isConnected = false;
let isWaitingForAnswer = false;
let evtSource = null;
let chatHistory = [];
let isMuted = localStorage.getItem("isMuted") === "true";

// --- ИНИЦИАЛИЗАЦИЯ ---

// 1. Темы
function applyTheme(theme) {
if (theme === "light") {
document.body.removeAttribute("data-theme");
} else {
document.body.setAttribute("data-theme", theme);
}
localStorage.setItem("theme", theme);
}

const savedTheme = localStorage.getItem("theme") || "light";
applyTheme(savedTheme);

themeMenuBtn.addEventListener("click", (e) => {
e.stopPropagation();
themeOptions.classList.toggle("active");
});

document.addEventListener("click", (e) => {
if (!themeOptions.contains(e.target) && e.target !== themeMenuBtn) {
themeOptions.classList.remove("active");
}
});

themeBtns.forEach(btn => {
btn.addEventListener("click", () => {
const theme = btn.dataset.theme;
applyTheme(theme);
themeOptions.classList.remove("active");
});
});

// 2. Звук (TTS)
function updateMuteIcon() {
muteBtn.textContent = isMuted ? "�" : "";
muteBtn.title = isMuted ? "Включить звук" : "Выключить звук";
}
updateMuteIcon();

muteBtn.addEventListener("click", () => {
isMuted = !isMuted;
localStorage.setItem("isMuted", isMuted);
updateMuteIcon();
if (isMuted) {
window.speechSynthesis.cancel();
}
});

function speakText(text) {
if (isMuted || !text) return;

// Очистка текста от markdown символов для озвучки
const cleanText = text.replace(/[*#`_\[\]]/g, "");

const utterance = new SpeechSynthesisUtterance(cleanText);
utterance.lang = "ru-RU";
window.speechSynthesis.speak(utterance);
}

// 3. Голосовой ввод (STT)
if ("webkitSpeechRecognition" in window) {
const recognition = new webkitSpeechRecognition();
recognition.continuous = false;
recognition.interimResults = false;
recognition.lang = "ru-RU";

recognition.onstart = () => {
micBtn.classList.add("listening");
};

recognition.onend = () => {
micBtn.classList.remove("listening");
};

recognition.onresult = (event) => {
const transcript = event.results[0][0].transcript;
promptInput.value = transcript;
promptInput.focus();
};

recognition.onerror = (event) => {
console.error("Speech recognition error", event.error);
micBtn.classList.remove("listening");
};

micBtn.addEventListener("click", () => {
if (micBtn.classList.contains("listening")) {
recognition.stop();
} else {
recognition.start();
}
});
} else {
micBtn.style.display = "none";
}

// --- ЛОГИКА ЧАТА ---

// Начальное состояние кнопок
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
promptInput.placeholder = "Введите задачу...";
addStatus("Connected to agent server.");
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

// Проверка здоровья сервера
setInterval(checkHealth, 1000);
checkHealth();

function addMessage(text, type) {
const div = document.createElement("div");
div.className = `message ${type}-message`;

if (type === "agent" && typeof marked !== "undefined") {
div.innerHTML = marked.parse(text);
// Озвучиваем ответ агента
speakText(text);
} else {
div.textContent = text;
}

chatContainer.appendChild(div);
chatContainer.scrollTop = chatContainer.scrollHeight;
}

function addStatus(text) {
const div = document.createElement("div");
div.className = "status-message";
div.textContent = text;
div.id = "current-status";

const prev = document.getElementById("current-status");
if (prev) prev.remove();

chatContainer.appendChild(div);
chatContainer.scrollTop = chatContainer.scrollHeight;
}

function getOrCreateThinkingDiv() {
if (!currentThinkingDiv) {
// Сворачиваем предыдущие блоки thinking
document.querySelectorAll(".thinking-content").forEach((el) => {
if (!el.classList.contains("collapsed")) {
el.classList.add("collapsed");
const header = el.previousElementSibling;
if (header) {
const icon = header.querySelector(".toggle-icon");
if (icon) icon.style.transform = "rotate(-90deg)";
}
}
});

const container = document.createElement("div");
container.className = "thinking-container";

const header = document.createElement("div");
header.className = "thinking-header";
header.innerHTML = "<span>Thinking Process</span><span class=\"toggle-icon\"></span>";

const content = document.createElement("div");
content.className = "thinking-content";

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
if (event.data === ": keepalive") return;

try {
const data = JSON.parse(event.data);

if (data.type === "token") {
const div = getOrCreateThinkingDiv();
div.textContent += data.content;
chatContainer.scrollTop = chatContainer.scrollHeight;
} else if (data.type === "status") {
addStatus(data.content);
} else if (data.type === "question") {
// Агент задает вопрос пользователю
addMessage(data.content, "agent");
isWaitingForAnswer = true;
promptInput.disabled = false;
sendBtn.disabled = false;
promptInput.focus();
promptInput.placeholder = "Введите ответ...";
addStatus("Ожидание ответа пользователя...");
}
} catch (e) {
console.error("Error parsing stream event:", e);
}
};

evtSource.onerror = (err) => {
console.error("EventSource failed:", err);
};
}

async function sendMessage() {
const text = promptInput.value.trim();
if (!text) return;

// Если мы в режиме ожидания ответа на вопрос агента
if (isWaitingForAnswer) {
addMessage(text, "user");
promptInput.value = "";
promptInput.disabled = true;
sendBtn.disabled = true;

try {
await fetch(ANSWER_URL, {
method: "POST",
headers: { "Content-Type": "application/json" },
body: JSON.stringify({ text: text }),
});
isWaitingForAnswer = false;
promptInput.placeholder = "Введите задачу...";
addStatus("Ответ отправлен...");
} catch (e) {
console.error("Failed to send answer", e);
addMessage("Ошибка отправки ответа", "agent");
promptInput.disabled = false;
sendBtn.disabled = false;
}
return;
}

// Обычный режим отправки задачи
currentThinkingDiv = null;

addMessage(text, "user");
promptInput.value = "";
promptInput.disabled = true;
sendBtn.disabled = true;
sendBtn.style.display = "none";
stopBtn.style.display = "flex";
addStatus("Агент думает...");

chatHistory.push({ role: "user", content: text });

try {
const response = await fetch(API_URL, {
method: "POST",
headers: {
"Content-Type": "application/json",
},
body: JSON.stringify({
query: text,
chat_history: chatHistory,
}),
});

const data = await response.json();

const status = document.getElementById("current-status");
if (status) status.remove();

if (data.status === "success") {
addMessage(data.result, "agent");
chatHistory.push({ role: "assistant", content: data.result });
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
currentThinkingDiv = null;
}
}

async function stopExecution() {
try {
await fetch(STOP_URL, { method: "POST" });
addStatus("Остановка...");
} catch (e) {
console.error("Failed to stop", e);
}
}

sendBtn.addEventListener("click", sendMessage);
stopBtn.addEventListener("click", stopExecution);

promptInput.addEventListener("keypress", (e) => {
if (e.key === "Enter") {
sendMessage();
}
});
});

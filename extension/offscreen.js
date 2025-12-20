// Send a message every 20 seconds to keep the service worker alive
setInterval(() => {
	chrome.runtime.sendMessage({ keepAlive: true });
}, 20000);

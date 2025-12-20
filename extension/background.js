chrome.sidePanel
	.setPanelBehavior({ openPanelOnActionClick: true })
	.catch((error) => console.error(error));
// --- Keep-Alive Logic ---
let creating; // A global promise to avoid concurrency issues

async function setupOffscreenDocument(path) {
	// Check if offscreen document already exists
	// Compatible with older Chrome versions where getContexts might not be available
	if (chrome.runtime.getContexts) {
		const existingContexts = await chrome.runtime.getContexts({
			contextTypes: ["OFFSCREEN_DOCUMENT"],
			documentUrls: [path],
		});
		if (existingContexts.length > 0) return;
	} else {
		// Fallback: just try to create it, if it exists it might throw or we catch it
		// But hasDocument is better if available
		if (
			chrome.offscreen.hasDocument &&
			(await chrome.offscreen.hasDocument())
		)
			return;
	}

	// Create offscreen document
	if (creating) {
		await creating;
	} else {
		creating = chrome.offscreen.createDocument({
			url: path,
			reasons: ["BLOBS"],
			justification: "Keep service worker alive",
		});
		await creating;
		creating = null;
	}
}

chrome.runtime.onStartup.addListener(() => {
	setupOffscreenDocument("offscreen.html");
});

chrome.runtime.onInstalled.addListener(() => {
	setupOffscreenDocument("offscreen.html");
});

// Listen for keep-alive messages
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
	if (msg.keepAlive) {
		// Received keep-alive message
	}
});

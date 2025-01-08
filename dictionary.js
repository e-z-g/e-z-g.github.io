const DICTIONARY_URL = 'https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt';
let DICTIONARY = new Set();

async function loadDictionary() {
    try {
        // Check if dictionary is cached in localStorage
        const cachedDictionary = localStorage.getItem('wordGameDictionary');
        if (cachedDictionary) {
            DICTIONARY = new Set(JSON.parse(cachedDictionary));
            console.log('Dictionary loaded from cache');
            return;
        }

        // If not cached, fetch from GitHub
        console.log('Fetching dictionary...');
        const response = await fetch(DICTIONARY_URL);
        const text = await response.text();
        
        // Convert to uppercase and filter out any empty lines or non-word characters
        const words = text
            .split('\n')
            .map(word => word.trim().toUpperCase())
            .filter(word => word && word.match(/^[A-Z]+$/));
        
        DICTIONARY = new Set(words);
        
        // Cache in localStorage for future use
        try {
            localStorage.setItem('wordGameDictionary', JSON.stringify([...DICTIONARY]));
            console.log('Dictionary cached successfully');
        } catch (e) {
            console.warn('Failed to cache dictionary (storage limit exceeded)');
        }
        
        console.log(`Dictionary loaded with ${DICTIONARY.size} words`);
    } catch (error) {
        console.error('Failed to load dictionary:', error);
        // Fallback to basic validation if dictionary fails to load
        DICTIONARY = new Set(words.flatMap(word => word.split('')));
    }
}

// Helper function to check if a string could start a valid word
function isValidWordStart(prefix) {
    prefix = prefix.toUpperCase();
    // Use Array.from() with early return for better performance
    return Array.from(DICTIONARY).some(word => word.startsWith(prefix));
}

// Helper function to check if a string is a complete valid word
function isValidWord(word) {
    return DICTIONARY.has(word.toUpperCase());
}

// Export the necessary functions and start loading the dictionary immediately
export {
    loadDictionary,
    isValidWordStart,
    isValidWord,
    DICTIONARY
};

// Start loading the dictionary as soon as this file is loaded
loadDictionary();

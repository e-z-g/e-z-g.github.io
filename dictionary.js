const DICTIONARY_URL = 'https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt';
let DICTIONARY = new Set();

async function loadDictionary() {
    try {
        // Check if dictionary is cached in localStorage
        const cachedDictionary = localStorage.getItem('wordGameDictionary');
        if (cachedDictionary) {
            window.loadingProgress?.(50, 'Loading cached dictionary...');
            DICTIONARY = new Set(JSON.parse(cachedDictionary));
            window.loadingProgress?.(100, 'Dictionary loaded from cache');
            return;
        }

        // If not cached, fetch from GitHub
        window.loadingProgress?.(10, 'Fetching dictionary...');
        const response = await fetch(DICTIONARY_URL);
        const reader = response.body.getReader();
        const contentLength = +response.headers.get('Content-Length');

        let receivedLength = 0;
        let chunks = [];
        
        while(true) {
            const {done, value} = await reader.read();
            
            if (done) break;
            
            chunks.push(value);
            receivedLength += value.length;
            
            // Calculate progress
            const progress = (receivedLength / contentLength) * 80;
            window.loadingProgress?.(progress, 'Loading dictionary...');
        }

        const text = new TextDecoder().decode(new Uint8Array(chunks.flat()));
        
        window.loadingProgress?.(90, 'Processing dictionary...');
        
        const words = text
            .split('\n')
            .map(word => word.trim().toUpperCase())
            .filter(word => word && word.match(/^[A-Z]+$/));
        
        DICTIONARY = new Set(words);
        
        try {
            window.loadingProgress?.(95, 'Caching dictionary...');
            localStorage.setItem('wordGameDictionary', JSON.stringify([...DICTIONARY]));
            console.log('Dictionary cached successfully');
        } catch (e) {
            console.warn('Failed to cache dictionary (storage limit exceeded)');
        }
        
        window.loadingProgress?.(100, 'Dictionary loaded!');
    } catch (error) {
        console.error('Failed to load dictionary:', error);
        window.loadingProgress?.(100, 'Using fallback dictionary');
        DICTIONARY = new Set(words.flatMap(word => word.split('')));
    }
}

function isValidWordStart(prefix) {
    prefix = prefix.toUpperCase();
    return Array.from(DICTIONARY).some(word => word.startsWith(prefix));
}

function isValidWord(word) {
    return DICTIONARY.has(word.toUpperCase());
}

export {
    loadDictionary,
    isValidWordStart,
    isValidWord,
    DICTIONARY
};

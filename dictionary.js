export const DICTIONARY_URL = 'https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt';
export let DICTIONARY = new Set();

// Add fallback dictionary
const FALLBACK_DICTIONARY = new Set([
    'PUZZLE', 'CODING', 'MASTER', 
    'GAME', 'PLAY', 'WORD', 'BUILD',
    'LEARN', 'CODE', 'WRITE', 'READ'
]);

export async function loadDictionary() {
    try {
        // Check if dictionary is cached in localStorage
        const cachedDictionary = localStorage.getItem('wordGameDictionary');
        if (cachedDictionary) {
            window.loadingProgress?.(50, 'Loading cached dictionary...');
            DICTIONARY = new Set(JSON.parse(cachedDictionary));
            window.loadingProgress?.(100, 'Dictionary loaded from cache');
            return;
        }

        // If not cached, fetch from GitHub with timeout
        window.loadingProgress?.(10, 'Fetching dictionary...');
        
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000); // 5 second timeout

        try {
            const response = await fetch(DICTIONARY_URL, {
                signal: controller.signal
            });
            
            if (!response.ok) throw new Error('Network response was not ok');
            
            const text = await response.text();
            clearTimeout(timeout);

            window.loadingProgress?.(90, 'Processing dictionary...');
            
            const words = text
                .split('\n')
                .map(word => word.trim().toUpperCase())
                .filter(word => word && word.match(/^[A-Z]+$/));
            
            DICTIONARY = new Set(words);
            
            try {
                window.loadingProgress?.(95, 'Caching dictionary...');
                localStorage.setItem('wordGameDictionary', JSON.stringify([...DICTIONARY]));
            } catch (e) {
                console.warn('Failed to cache dictionary (storage limit exceeded)');
            }
            
            window.loadingProgress?.(100, 'Dictionary loaded!');
        } catch (error) {
            throw new Error('Failed to fetch dictionary');
        }
    } catch (error) {
        console.warn('Using fallback dictionary:', error);
        window.loadingProgress?.(100, 'Using fallback dictionary');
        DICTIONARY = FALLBACK_DICTIONARY;
    }
}

export function isValidWordStart(prefix) {
    prefix = prefix.toUpperCase();
    return Array.from(DICTIONARY).some(word => word.startsWith(prefix));
}

export function isValidWord(word) {
    return DICTIONARY.has(word.toUpperCase());
}

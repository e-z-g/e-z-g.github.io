import { loadDictionary, isValidWordStart, isValidWord, DICTIONARY } from './dictionary.js';
import { createConfetti } from './confetti.js';


// Add loading screen handling
const loadingScreen = document.createElement('div');
loadingScreen.className = 'loading-screen';
loadingScreen.innerHTML = `
    <div class="loading-content">
        <h2>Loading Dictionary...</h2>
        <div class="loading-spinner"></div>
    </div>
`;
document.body.appendChild(loadingScreen);







// Add progress tracking
window.loadingProgress = (progress, status) => {
    const progressFill = document.getElementById('progress-fill');
    const loadingStatus = document.getElementById('loading-status');
    progressFill.style.width = `${progress}%`;
    loadingStatus.textContent = status;
};







// Add loading screen styles to the CSS file
const styles = `
.loading-screen {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.9);
    display: none;
    justify-content: center;
    align-items: center;
    z-index: 2000;
}

.loading-content {
    text-align: center;
    color: white;
}

.loading-spinner {
    width: 50px;
    height: 50px;
    border: 5px solid #f3f3f3;
    border-top: 5px solid #3498db;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 20px auto;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
`;

// Add styles to document
const styleSheet = document.createElement("style");
styleSheet.textContent = styles;
document.head.appendChild(styleSheet);


// Game configuration from URL parameters
const urlParams = new URLSearchParams(window.location.search);
const words = [
    urlParams.get('word1') || 'PUZZLE',
    urlParams.get('word2') || 'CODING',
    urlParams.get('word3') || 'MASTER'
];
const backgroundImages = [
    urlParams.get('image1') || 'https://example.com/bg1.jpg',
    urlParams.get('image2') || 'https://example.com/bg2.jpg',
    urlParams.get('image3') || 'https://example.com/bg3.jpg'
];
const initialLives = parseInt(urlParams.get('lives')) || 3;

// Game state
let currentLevel = 0;
let currentWord = '';
let collectedLetters = '';
let lives = initialLives;
let baseSpeed = 2;
let currentSpeed = baseSpeed;
let letterElements = [];
let activeDictionary = new Set();
let isGameActive = true;
let animationFrameId = null;

// DOM elements
const gameContainer = document.getElementById('game-container');
const backgroundImage = document.getElementById('background-image');
const lettersContainer = document.getElementById('letters-container');
const player = document.getElementById('player');
const livesDisplay = document.getElementById('lives');
const wordProgress = document.getElementById('word-progress');
const levelNumber = document.getElementById('level-number');
const message = document.getElementById('message');
const gameOverScreen = document.getElementById('game-over');
const victoryScreen = document.getElementById('victory');

// Initialize dictionary
async function initializeDictionary() {
    if (DICTIONARY.size === 0) {
        loadingScreen.style.display = 'flex';
        await loadDictionary();
        loadingScreen.style.display = 'none';
    }
}

// Check if letters could form a valid word
function couldFormValidWord(letters) {
    // First check if it's already a complete valid word
    if (isValidWord(letters)) return true;
    // Then check if it could start a valid word
    return isValidWordStart(letters);
}

// Create letter elements
function createLetters() {
function createLetters() {
    lettersContainer.innerHTML = '';
    letterElements = [];
    
    const word = words[currentLevel].toUpperCase(); // Force uppercase
    const distinctColors = generateDistinctColors(word.length);


    
[...word].forEach((letter, index) => {
        const element = document.createElement('div');
        element.className = 'letter';
        element.textContent = letter;
        element.style.backgroundColor = distinctColors[index];
        element.style.textTransform = 'uppercase'; // Force uppercase
        element.style.fontWeight = 'bold';
        element.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
        element.style.border = '2px solid rgba(255, 255, 255, 0.3)';
        
        // Add hover effect
        element.addEventListener('mouseover', () => {
            element.style.transform = 'scale(1.1)';
            element.style.transition = 'transform 0.2s ease';
        });
        
        element.addEventListener('mouseout', () => {
            element.style.transform = 'scale(1)';
        });
        // Add touch/click handlers
        element.addEventListener('mousedown', () => handleLetterClick(letter));
        element.addEventListener('touchstart', (e) => {
            e.preventDefault();
            handleLetterClick(letter);
        });
        
        lettersContainer.appendChild(element);
        letterElements.push({
            element,
            x: Math.random() * (window.innerWidth - 60),
            y: Math.random() * (window.innerHeight - 60),
            dx: (Math.random() - 0.5) * currentSpeed,
            dy: (Math.random() - 0.5) * currentSpeed,
            mass: 1
        });
    });
}

function generateDistinctColors(count) {
    const colors = [];
    for (let i = 0; i < count; i++) {
        colors.push(`hsl(${(360 / count) * i}, 70%, 50%)`);
    }
    return colors;
}

// Game loop
function gameLoop() {
    if (!isGameActive) return;
    updateLetters();
    animationFrameId = requestAnimationFrame(gameLoop);
}

// Update letter positions
function updateLetters() {
    // First update positions
    letterElements.forEach((letter, i) => {
        // Update position
        letter.x += letter.dx * currentSpeed;
        letter.y += letter.dy * currentSpeed;

        // Bounce off walls with padding
        if (letter.x <= 0 || letter.x >= window.innerWidth - 60) {
            letter.dx *= -1;
            letter.x = Math.max(0, Math.min(letter.x, window.innerWidth - 60));
        }
        if (letter.y <= 60 || letter.y >= window.innerHeight - 60) {
            letter.dy *= -1;
            letter.y = Math.max(60, Math.min(letter.y, window.innerHeight - 60));
        }

        // Check collisions with other letters
        for (let j = i + 1; j < letterElements.length; j++) {
            const other = letterElements[j];
            
            // Calculate distance between letters
            const dx = other.x - letter.x;
            const dy = other.y - letter.y;
            const distance = Math.sqrt(dx * dx + dy * dy);
            
            // If letters are colliding (assuming letters are 60px wide)
            const minDistance = 60;
            if (distance < minDistance) {
                // Calculate collision response
                const angle = Math.atan2(dy, dx);
                const sin = Math.sin(angle);
                const cos = Math.cos(angle);

                // Rotate velocities
                const vx1 = letter.dx * cos + letter.dy * sin;
                const vy1 = letter.dy * cos - letter.dx * sin;
                const vx2 = other.dx * cos + other.dy * sin;
                const vy2 = other.dy * cos - other.dx * sin;

                // Swap the velocities
                letter.dx = vx2 * cos - vy1 * sin;
                letter.dy = vy1 * cos + vx2 * sin;
                other.dx = vx1 * cos - vy2 * sin;
                other.dy = vy2 * cos + vx1 * sin;

                // Move letters apart to prevent sticking
                const overlap = minDistance - distance;
                const moveX = (overlap * cos) / 2;
                const moveY = (overlap * sin) / 2;

                letter.x -= moveX;
                letter.y -= moveY;
                other.x += moveX;
                other.y += moveY;
            }
        }

        // Apply position
        letter.element.style.left = `${letter.x}px`;
        letter.element.style.top = `${letter.y}px`;
    });
}

// Handle letter collection
function handleLetterClick(letter) {
    if (!isGameActive) return;
    
    const expectedLetter = words[currentLevel][collectedLetters.length].toUpperCase();
    
    if (letter.toUpperCase() === expectedLetter) {
        // Add collection animation
        const letterElement = letterElements.find(l => l.element.textContent === letter).element;
        letterElement.style.transform = 'scale(1.5)';
        letterElement.style.opacity = '0';
        setTimeout(() => letterElement.style.display = 'none', 300);
    } else {
        // Check if this could form a valid word
        if (couldFormValidWord(collectedLetters + letter)) {
            showMessage('Not quite!', 'warning');
            currentSpeed *= 1.2;
        } else {
            showMessage('Wrong!', 'danger');
            lives--;
            updateLives();
            if (lives <= 0) {
                gameOver();
            }
        }
    }
    
    updateWordProgress();
}

// Update display elements
function updateWordProgress() {
    const wordLength = words[currentLevel].length;
    const progress = collectedLetters.split('').map(l => l).join('');
    const remaining = '◌'.repeat(wordLength - progress.length); // Using a different symbol for empty spaces
    wordProgress.textContent = (progress + remaining).toUpperCase();
}

function updateLives() {
    livesDisplay.innerHTML = '❤️'.repeat(lives);
}

function showMessage(text, type) {
    message.textContent = text;
    message.className = `message message-${type}`;
    message.style.opacity = 1;
    setTimeout(() => {
        message.style.opacity = 0;
    }, 1000);
}

// Level management
function nextLevel() {
    currentLevel++;
    if (currentLevel >= words.length) {
        victory();
    } else {
        startLevel();
    }
}

async function startLevel() {
    collectedLetters = '';
    currentSpeed = baseSpeed;
    levelNumber.textContent = currentLevel + 1;
    backgroundImage.style.backgroundImage = `url(${backgroundImages[currentLevel]})`;
    await initializeDictionary();
    createLetters();
    updateWordProgress();
}


// Game state changes
function gameOver() {
    isGameActive = false;
    cancelAnimationFrame(animationFrameId);
    gameOverScreen.classList.remove('hidden');
    const finalWords = document.getElementById('final-words');
    finalWords.textContent = `Level ${currentLevel + 1}: ${collectedLetters}`;
}

function victory() {
    isGameActive = false;
    cancelAnimationFrame(animationFrameId);
    victoryScreen.classList.remove('hidden');
    document.getElementById('final-image').style.backgroundImage = 
        `url(${backgroundImages[2]})`;
    const completionWords = document.getElementById('completion-words');
    completionWords.textContent = words.join(' ➔ ');
    
// Victory celebration
    const celebrateVictory = () => {
        createConfetti({
            particleCount: 30,
            spread: 90,
            origin: { y: Math.random() * 0.8 }
        });
        
        if (document.visibilityState !== 'hidden') {
            setTimeout(celebrateVictory, 500);
        }
    };
    
    celebrateVictory();
}

// Handle mobile touch events
function handleTouchMove(e) {
    e.preventDefault();
    const touch = e.touches[0];
    updatePlayerPosition(touch.pageX, touch.pageY);
}

function handleMouseMove(e) {
    updatePlayerPosition(e.pageX, e.pageY);
}

function updatePlayerPosition(x, y) {
    if (!isGameActive) return;
    player.style.left = (x - player.offsetWidth / 2) + 'px';
    player.style.top = (y - player.offsetHeight / 2) + 'px';
}

// Event listeners
document.addEventListener('mousemove', handleMouseMove);
document.addEventListener('touchmove', handleTouchMove, { passive: false });
document.getElementById('restart-button').addEventListener('click', initGame);
document.getElementById('play-again-button').addEventListener('click', initGame);

// Handle window resize
window.addEventListener('resize', () => {
    letterElements.forEach(letter => {
        letter.x = Math.min(letter.x, window.innerWidth - 60);
        letter.y = Math.min(letter.y, window.innerHeight - 60);
    });
});

// Initialize game
async function initGame() {
    const loadingScreen = document.getElementById('loading-screen');
    loadingScreen.style.display = 'flex';
    
    currentLevel = 0;
    lives = initialLives;
    isGameActive = true;
    gameOverScreen.classList.add('hidden');
    victoryScreen.classList.add('hidden');
    
    await loadDictionary();
    updateLives();
    await startLevel();
    
    loadingScreen.style.display = 'none';
    gameLoop();
}

// Start the game
initGame();

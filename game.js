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
function initializeDictionary() {
    const wordLength = words[currentLevel].length;
    activeDictionary = new Set(
        DICTIONARY.filter(word => word.length <= wordLength)
    );
}

// Check if letters could form a valid word
function couldFormValidWord(letters) {
    const pattern = new RegExp(`^${letters}`);
    return Array.from(activeDictionary).some(word => pattern.test(word));
}

// Create letter elements
function createLetters() {
    lettersContainer.innerHTML = '';
    letterElements = [];
    
    const uniqueLetters = [...new Set(words[currentLevel])];
    uniqueLetters.forEach(letter => {
        const element = document.createElement('div');
        element.className = 'letter';
        element.textContent = letter;
        element.style.backgroundColor = `hsl(${Math.random() * 360}, 70%, 50%)`;
        element.style.animationDelay = `${Math.random() * 2}s`;
        
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
            dy: (Math.random() - 0.5) * currentSpeed
        });
    });
}

// Game loop
function gameLoop() {
    if (!isGameActive) return;
    updateLetters();
    animationFrameId = requestAnimationFrame(gameLoop);
}

// Update letter positions
function updateLetters() {
    letterElements.forEach(letter => {
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

        // Apply position
        letter.element.style.left = `${letter.x}px`;
        letter.element.style.top = `${letter.y}px`;
    });
}

// Handle letter collection
function handleLetterClick(letter) {
    if (!isGameActive) return;
    
    const expectedLetter = words[currentLevel][collectedLetters.length];
    
    if (letter === expectedLetter) {
        // Correct letter
        showMessage('Correct!', 'success');
        collectedLetters += letter;
        currentSpeed = baseSpeed;
        
        if (collectedLetters === words[currentLevel]) {
            // Word completed
            confetti({
                particleCount: 100,
                spread: 70,
                origin: { y: 0.6 }
            });
            setTimeout(nextLevel, 1500);
        }
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
    const remaining = '_'.repeat(wordLength - progress.length);
    wordProgress.textContent = progress + remaining;
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

function startLevel() {
    collectedLetters = '';
    currentSpeed = baseSpeed;
    levelNumber.textContent = currentLevel + 1;
    backgroundImage.style.backgroundImage = `url(${backgroundImages[currentLevel]})`;
    createLetters();
    initializeDictionary();
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
    completionWords.textContent = words.join(' → ');
    
    // Victory fireworks
    const duration = 15 * 1000;
    const animationEnd = Date.now() + duration;
    let skew = 1;

    function randomInRange(min, max) {
        return Math.random() * (max - min) + min;
    }

    (function frame() {
        const timeLeft = animationEnd - Date.now();
        if (timeLeft <= 0) return;
        
        skew = Math.max(0.8, skew - 0.001);

        confetti({
            particleCount: 1,
            startVelocity: 0,
            ticks: Math.max(200, 500 * (timeLeft / duration)),
            origin: {
                x: Math.random(),
                y: Math.random() * skew - 0.2
            },
            colors: ['#FF0000', '#FFD700', '#00FF00', '#0000FF', '#FF00FF'],
            shapes: ['circle', 'square'],
            gravity: randomInRange(0.4, 0.6),
            scalar: randomInRange(0.8, 1.2),
            drift: randomInRange(-0.4, 0.4)
        });

        requestAnimationFrame(frame);
    }());
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
function initGame() {
    currentLevel = 0;
    lives = initialLives;
    isGameActive = true;
    gameOverScreen.classList.add('hidden');
    victoryScreen.classList.add('hidden');
    updateLives();
    startLevel();
    gameLoop();
}

// Start the game
initGame();

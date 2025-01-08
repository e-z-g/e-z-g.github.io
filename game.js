// Get URL parameters for game configuration
const urlParams = new URLSearchParams(window.location.search);
const gameSpeed = parseFloat(urlParams.get('speed')) || 1.0; // Default speed multiplier is 1.0
const starSize = parseInt(urlParams.get('size')) || 40; // Default star size is 40px

// Game elements
const star = document.getElementById('star');
const player = document.getElementById('player');
const scoreElement = document.getElementById('scoreValue');
const timeElement = document.getElementById('timeValue');
const gameOverScreen = document.getElementById('gameOver');
const finalScoreElement = document.getElementById('finalScore');

// Game state
let score = 0;
let timeLeft = 30;
let gameInterval;
let moveInterval;
let isGameActive = true;

// Apply URL parameters
star.style.fontSize = `${starSize}px`;
player.style.fontSize = `${starSize}px`;

// Initialize star position
function moveStarRandomly() {
    const maxX = window.innerWidth - star.offsetWidth;
    const maxY = window.innerHeight - star.offsetHeight;
    star.style.left = Math.random() * maxX + 'px';
    star.style.top = Math.random() * maxY + 'px';
}

// Move player to follow mouse
document.addEventListener('mousemove', (e) => {
    if (isGameActive) {
        player.style.left = (e.pageX - player.offsetWidth / 2) + 'px';
        player.style.top = (e.pageY - player.offsetHeight / 2) + 'px';
    }
});

// Check for collisions
function checkCollision() {
    const starRect = star.getBoundingClientRect();
    const playerRect = player.getBoundingClientRect();

    if (!(playerRect.right < starRect.left || 
          playerRect.left > starRect.right || 
          playerRect.bottom < starRect.top || 
          playerRect.top > starRect.bottom)) {
        score++;
        scoreElement.textContent = score;
        moveStarRandomly();
    }
}

// Game timer
function updateTimer() {
    timeLeft--;
    timeElement.textContent = timeLeft;
    
    if (timeLeft <= 0) {
        endGame();
    }
}

// End game
function endGame() {
    isGameActive = false;
    clearInterval(gameInterval);
    clearInterval(moveInterval);
    finalScoreElement.textContent = score;
    gameOverScreen.classList.remove('hidden');
}

// Reset game
function resetGame() {
    score = 0;
    timeLeft = 30;
    isGameActive = true;
    scoreElement.textContent = score;
    timeElement.textContent = timeLeft;
    gameOverScreen.classList.add('hidden');
    moveStarRandomly();
    startGame();
}

// Start game
function startGame() {
    moveStarRandomly();
    gameInterval = setInterval(updateTimer, 1000);
    moveInterval = setInterval(checkCollision, 1000 / (60 * gameSpeed)); // Adjust check rate based on speed
}

// Initialize game
startGame();

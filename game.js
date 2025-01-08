// Get URL parameters for game configuration
const urlParams = new URLSearchParams(window.location.search);
const gameSpeed = parseFloat(urlParams.get('speed')) || 1.0;
const elementSize = parseInt(urlParams.get('size')) || 40;
const playerImageUrl = urlParams.get('playerImage') || 'https://example.com/hand.png';
const starImageUrl = urlParams.get('starImage') || 'https://example.com/star.png';
const obstacleImageUrl = urlParams.get('obstacleImage') || 'https://example.com/obstacle.png';
const obstacleCount = parseInt(urlParams.get('obstacles')) || 5;

// Game elements
const star = document.getElementById('star');
const player = document.getElementById('player');
const obstaclesContainer = document.getElementById('obstacles');
const scoreElement = document.getElementById('scoreValue');
const timeElement = document.getElementById('timeValue');
const gameOverScreen = document.getElementById('gameOver');
const finalScoreElement = document.getElementById('finalScore');

// Set up images
star.src = starImageUrl;
player.src = playerImageUrl;

// Apply sizes
star.style.width = `${elementSize}px`;
star.style.height = `${elementSize}px`;
player.style.width = `${elementSize}px`;
player.style.height = `${elementSize}px`;

// Game state
let score = 0;
let timeLeft = 30;
let gameInterval;
let moveInterval;
let obstacleIntervals = [];
let isGameActive = true;

// Create obstacles
function createObstacles() {
    for (let i = 0; i < obstacleCount; i++) {
        const obstacle = document.createElement('img');
        obstacle.src = obstacleImageUrl;
        obstacle.className = 'obstacle';
        obstacle.style.width = `${elementSize}px`;
        obstacle.style.height = `${elementSize}px`;
        obstaclesContainer.appendChild(obstacle);
        moveObstacleRandomly(obstacle);
        
        // Set up periodic movement for each obstacle
        const intervalSpeed = 2000 + Math.random() * 2000; // Random speed between 2-4 seconds
        const interval = setInterval(() => {
            if (isGameActive) {
                moveObstacleRandomly(obstacle);
            }
        }, intervalSpeed);
        obstacleIntervals.push(interval);
    }
}

// Move obstacle to random position
function moveObstacleRandomly(obstacle) {
    const maxX = window.innerWidth - obstacle.offsetWidth;
    const maxY = window.innerHeight - obstacle.offsetHeight;
    const randomX = Math.random() * maxX;
    const randomY = Math.random() * maxY;
    
    obstacle.style.left = randomX + 'px';
    obstacle.style.top = randomY + 'px';
    
    // Add floating animation with random duration
    obstacle.style.animation = `float ${3 + Math.random() * 2}s linear infinite`;
}

// Initialize star position
function moveStarRandomly() {
    const maxX = window.innerWidth - star.offsetWidth;
    const maxY = window.innerHeight - star.offsetHeight;
    const newX = Math.random() * maxX;
    const newY = Math.random() * maxY;
    
    // Ensure star doesn't spawn too close to any obstacle
    const starRect = {
        left: newX - elementSize,
        right: newX + elementSize,
        top: newY - elementSize,
        bottom: newY + elementSize
    };
    
    const obstacles = document.querySelectorAll('.obstacle');
    for (const obstacle of obstacles) {
        const obstacleRect = obstacle.getBoundingClientRect();
        if (isColliding(starRect, obstacleRect)) {
            moveStarRandomly(); // Try again if too close to obstacle
            return;
        }
    }
    
    star.style.left = newX + 'px';
    star.style.top = newY + 'px';
}

// Move player to follow mouse
document.addEventListener('mousemove', (e) => {
    if (isGameActive) {
        const x = e.pageX - player.offsetWidth / 2;
        const y = e.pageY - player.offsetHeight / 2;
        player.style.left = x + 'px';
        player.style.top = y + 'px';
    }
});

// Check for collisions
function checkCollision() {
    if (!isGameActive) return;
    
    const playerRect = player.getBoundingClientRect();
    const starRect = star.getBoundingClientRect();
    const obstacles = document.querySelectorAll('.obstacle');
    
    // Check if player caught the star
    if (isColliding(playerRect, starRect)) {
        score++;
        scoreElement.textContent = score;
        moveStarRandomly();
    }
    
    // Check if player hit any obstacle
    for (const obstacle of obstacles) {
        const obstacleRect = obstacle.getBoundingClientRect();
        if (isColliding(playerRect, obstacleRect)) {
            endGame();
            return;
        }
    }
}

// Helper function to check collision between two rectangles
function isColliding(rect1, rect2) {
    return !(rect1.right < rect2.left || 
            rect1.left > rect2.right || 
            rect1.bottom < rect2.top || 
            rect1.top > rect2.bottom);
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
    obstacleIntervals.forEach(interval => clearInterval(interval));
    finalScoreElement.textContent = score;
    gameOverScreen.classList.remove('hidden');
}

// Reset game
function resetGame() {
    // Clear existing obstacles
    obstaclesContainer.innerHTML = '';
    obstacleIntervals.forEach(interval => clearInterval(interval));
    obstacleIntervals = [];
    
    // Reset game state
    score = 0;
    timeLeft = 30;
    isGameActive = true;
    scoreElement.textContent = score;
    timeElement.textContent = timeLeft;
    gameOverScreen.classList.add('hidden');
    
    // Restart game
    createObstacles();
    moveStarRandomly();
    startGame();
}

// Start game
function startGame() {
    gameInterval = setInterval(updateTimer, 1000);
    moveInterval = setInterval(checkCollision, 1000 / (60 * gameSpeed));
}

// Initialize game
createObstacles();
moveStarRandomly();
startGame();

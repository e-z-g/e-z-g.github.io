// Update confetti.js
export function createConfetti(options = {}) {
    const {
        particleCount = 50,
        spread = 70,
        colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff'],
        origin = { y: 0.5 },
        gravity = 1,
        ticks = 200
    } = options;

    const container = document.createElement('div');
    container.style.position = 'fixed';
    container.style.top = '0';
    container.style.left = '0';
    container.style.width = '100%';
    container.style.height = '100%';
    container.style.pointerEvents = 'none';
    container.style.zIndex = '1000';
    document.body.appendChild(container);

    const particles = [];

    for (let i = 0; i < particleCount; i++) {
        const particle = document.createElement('div');
        particle.style.position = 'absolute';
        particle.style.width = '10px';
        particle.style.height = '10px';
        particle.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
        particle.style.borderRadius = '50%';
        particle.style.left = '50%';
        particle.style.top = `${origin.y * 100}%`;

        const angle = (Math.random() * spread - spread/2) * (Math.PI/180);
        const velocity = 15 + Math.random() * 15;
        const vx = Math.cos(angle) * velocity;
        const vy = Math.sin(angle) * velocity;

        let x = 0;
        let y = 0;
        let tick = 0;
        
        function updatePosition(timestamp) {
            if (!particle.parentNode || tick >= ticks) {
                container.removeChild(particle);
                particles.splice(particles.indexOf(particle), 1);
                if (particles.length === 0) {
                    document.body.removeChild(container);
                }
                return;
            }
            
            x += vx;
            y += vy;
            vy += gravity * 0.1; // Smoother gravity
            
            particle.style.transform = `translate(${x}px, ${y}px) rotate(${x * 0.5}deg)`;
            particle.style.opacity = 1 - (tick / ticks);
            
            tick++;
            requestAnimationFrame(updatePosition);
        }

        particles.push(particle);
        container.appendChild(particle);
        requestAnimationFrame(updatePosition);
    }
}

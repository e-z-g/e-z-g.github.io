export function createConfetti(options = {}) {
    const {
        particleCount = 50,
        spread = 70,
        colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff']
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

    for (let i = 0; i < particleCount; i++) {
        const particle = document.createElement('div');
        particle.style.position = 'absolute';
        particle.style.width = '10px';
        particle.style.height = '10px';
        particle.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
        particle.style.borderRadius = '50%';
        particle.style.left = '50%';
        particle.style.top = `${options.origin?.y * 100 || 50}%`;

        // Random initial velocity
        const angle = (Math.random() * spread - spread/2) * (Math.PI/180);
        const velocity = 15 + Math.random() * 15;
        const vx = Math.cos(angle) * velocity;
        const vy = Math.sin(angle) * velocity;

        // Animation
        let x = 0;
        let y = 0;
        let opacity = 1;
        
        function updatePosition(timestamp) {
            if (!particle.parentNode) return;
            
            x += vx;
            y += vy + 0.5; // Add gravity
            opacity -= 0.01;
            
            if (opacity <= 0) {
                container.removeChild(particle);
                if (container.children.length === 0) {
                    document.body.removeChild(container);
                }
                return;
            }
            
            particle.style.transform = `translate(${x}px, ${y}px)`;
            particle.style.opacity = opacity;
            
            requestAnimationFrame(updatePosition);
        }

        container.appendChild(particle);
        requestAnimationFrame(updatePosition);
    }
}

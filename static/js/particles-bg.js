/* ========================================================================
   PARTICLES BACKGROUND - Theme-Aware Animated Particles
   ======================================================================== */

class ParticlesBackground {
    constructor() {
        this.canvas = null;
        this.ctx = null;
        this.particles = [];
        this.particleCount = 80; // Increased from 50 for more particles
        this.maxDistance = 150;
        this.animationId = null;
        this.mouseX = 0;
        this.mouseY = 0;
        
        this.init();
    }
    
    init() {
        // Create canvas
        this.canvas = document.getElementById('particles-canvas');
        if (!this.canvas) {
            const bg = document.getElementById('particles-background');
            if (bg) {
                this.canvas = document.createElement('canvas');
                this.canvas.id = 'particles-canvas';
                bg.appendChild(this.canvas);
            } else {
                return;
            }
        }
        
        this.ctx = this.canvas.getContext('2d');
        this.resize();
        this.createParticles();
        
        // Event listeners
        window.addEventListener('resize', () => this.resize());
        document.addEventListener('mousemove', (e) => {
            this.mouseX = e.clientX;
            this.mouseY = e.clientY;
        });
        
        // Start animation
        this.animate();
    }
    
    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }
    
    getThemeColors() {
        const theme = document.documentElement.getAttribute('data-theme') || 'dark';
        
        if (theme === 'dark') {
            return {
                primary: 'rgba(0, 217, 255, 0.6)',      // Cyan
                secondary: 'rgba(255, 61, 113, 0.6)',   // Pink
                line: 'rgba(0, 217, 255, 0.15)'         // Cyan faint
            };
        } else {
            return {
                primary: 'rgba(0, 153, 204, 0.6)',      // Blue
                secondary: 'rgba(216, 27, 96, 0.6)',    // Pink
                line: 'rgba(0, 153, 204, 0.1)'          // Blue faint
            };
        }
    }
    
    createParticles() {
        this.particles = [];
        const colors = this.getThemeColors();
        
        for (let i = 0; i < this.particleCount; i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * 1.2, // Faster movement (was 0.5)
                vy: (Math.random() - 0.5) * 1.2, // Faster movement (was 0.5)
                radius: Math.random() * 3 + 2, // Larger particles (was 2 + 1)
                color: Math.random() > 0.5 ? colors.primary : colors.secondary
            });
        }
    }
    
    drawParticle(particle) {
        this.ctx.beginPath();
        this.ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        this.ctx.fillStyle = particle.color;
        this.ctx.fill();
        
        // Add glow effect
        this.ctx.shadowBlur = 10;
        this.ctx.shadowColor = particle.color;
        this.ctx.fill();
        this.ctx.shadowBlur = 0;
    }
    
    drawLines() {
        const colors = this.getThemeColors();
        
        for (let i = 0; i < this.particles.length; i++) {
            for (let j = i + 1; j < this.particles.length; j++) {
                const dx = this.particles[i].x - this.particles[j].x;
                const dy = this.particles[i].y - this.particles[j].y;
                const distance = Math.sqrt(dx * dx + dy * dy);
                
                if (distance < this.maxDistance) {
                    const opacity = (1 - distance / this.maxDistance) * 0.3;
                    this.ctx.beginPath();
                    this.ctx.strokeStyle = colors.line.replace('0.15', opacity);
                    this.ctx.lineWidth = 0.5;
                    this.ctx.moveTo(this.particles[i].x, this.particles[i].y);
                    this.ctx.lineTo(this.particles[j].x, this.particles[j].y);
                    this.ctx.stroke();
                }
            }
        }
    }
    
    updateParticles() {
        const colors = this.getThemeColors();
        
        this.particles.forEach((particle, index) => {
            // Update position
            particle.x += particle.vx;
            particle.y += particle.vy;
            
            // Bounce off edges
            if (particle.x < 0 || particle.x > this.canvas.width) {
                particle.vx *= -1;
            }
            if (particle.y < 0 || particle.y > this.canvas.height) {
                particle.vy *= -1;
            }
            
            // Keep within bounds
            particle.x = Math.max(0, Math.min(this.canvas.width, particle.x));
            particle.y = Math.max(0, Math.min(this.canvas.height, particle.y));
            
            // Update color based on theme
            particle.color = Math.random() > 0.5 ? colors.primary : colors.secondary;
            
            // Mouse interaction
            const dx = this.mouseX - particle.x;
            const dy = this.mouseY - particle.y;
            const distance = Math.sqrt(dx * dx + dy * dy);
            
            if (distance < 100) {
                particle.vx -= dx * 0.0001;
                particle.vy -= dy * 0.0001;
            }
        });
    }
    
    animate() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        this.updateParticles();
        this.drawLines();
        
        this.particles.forEach(particle => {
            this.drawParticle(particle);
        });
        
        this.animationId = requestAnimationFrame(() => this.animate());
    }
    
    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
        window.removeEventListener('resize', () => this.resize());
    }
    
    updateTheme() {
        // Recreate particles with new theme colors
        this.createParticles();
    }
}

// Initialize particles when DOM is ready
let particlesInstance = null;

document.addEventListener('DOMContentLoaded', function() {
    particlesInstance = new ParticlesBackground();
    
    // Listen for theme changes
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            setTimeout(() => {
                if (particlesInstance) {
                    particlesInstance.updateTheme();
                }
            }, 100);
        });
    }
});

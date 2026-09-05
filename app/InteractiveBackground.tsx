'use client';

import { useEffect, useRef } from 'react';

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  depth: number;
  phase: number;
  tone: number;
};

type Ripple = { x: number; y: number; life: number };

export default function InteractiveBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const pointer = { x: window.innerWidth * 0.68, y: window.innerHeight * 0.34, active: false };
    const ripples: Ripple[] = [];
    let particles: Particle[] = [];
    let width = window.innerWidth;
    let height = window.innerHeight;
    let frame = 0;
    let animationId = 0;

    const createParticles = () => {
      const count = Math.max(58, Math.min(118, Math.round((width * height) / 17500)));
      particles = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        radius: 0.65 + Math.random() * 2.15,
        depth: 0.35 + Math.random() * 0.9,
        phase: Math.random() * Math.PI * 2,
        tone: Math.random(),
      }));
    };

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      const density = Math.min(window.devicePixelRatio || 1, 1.6);
      canvas.width = Math.round(width * density);
      canvas.height = Math.round(height * density);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(density, 0, 0, density, 0, 0);
      createParticles();
    };

    const movePointer = (event: PointerEvent) => {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.active = true;
    };

    const leavePointer = () => { pointer.active = false; };
    const addRipple = (event: PointerEvent) => ripples.push({ x: event.clientX, y: event.clientY, life: 0 });

    const render = () => {
      context.clearRect(0, 0, width, height);
      frame += reducedMotion ? 0 : 0.012;

      if (pointer.active) {
        const glow = context.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, 230);
        glow.addColorStop(0, 'rgba(84, 178, 255, 0.085)');
        glow.addColorStop(0.45, 'rgba(54, 219, 207, 0.035)');
        glow.addColorStop(1, 'rgba(0, 0, 0, 0)');
        context.fillStyle = glow;
        context.fillRect(pointer.x - 230, pointer.y - 230, 460, 460);
      }

      particles.forEach((particle) => {
        if (!reducedMotion) {
          particle.vx += Math.sin(frame + particle.phase) * 0.0008;
          particle.vy += Math.cos(frame * 0.8 + particle.phase) * 0.0008;

          if (pointer.active) {
            const dx = pointer.x - particle.x;
            const dy = pointer.y - particle.y;
            const distance = Math.hypot(dx, dy);
            if (distance < 190 && distance > 1) {
              const pull = (1 - distance / 190) * 0.012 * particle.depth;
              particle.vx += (dx / distance) * pull;
              particle.vy += (dy / distance) * pull;
            }
          }

          particle.vx *= 0.992;
          particle.vy *= 0.992;
          particle.x += particle.vx;
          particle.y += particle.vy;
          if (particle.x < -12) particle.x = width + 12;
          if (particle.x > width + 12) particle.x = -12;
          if (particle.y < -12) particle.y = height + 12;
          if (particle.y > height + 12) particle.y = -12;
        }
      });

      for (let i = 0; i < particles.length; i += 1) {
        for (let j = i + 1; j < particles.length; j += 1) {
          const first = particles[i];
          const second = particles[j];
          const distance = Math.hypot(first.x - second.x, first.y - second.y);
          if (distance < 108) {
            context.beginPath();
            context.moveTo(first.x, first.y);
            context.lineTo(second.x, second.y);
            context.strokeStyle = `rgba(75, 157, 198, ${(1 - distance / 108) * 0.075})`;
            context.lineWidth = 0.65;
            context.stroke();
          }
        }
      }

      particles.forEach((particle) => {
        const pulse = reducedMotion ? 0.75 : 0.62 + Math.sin(frame * 3 + particle.phase) * 0.24;
        const parallaxX = pointer.active ? (pointer.x - width / 2) * 0.008 * particle.depth : 0;
        const parallaxY = pointer.active ? (pointer.y - height / 2) * 0.008 * particle.depth : 0;
        const x = particle.x + parallaxX;
        const y = particle.y + parallaxY;
        context.beginPath();
        context.arc(x, y, particle.radius * (0.85 + pulse * 0.25), 0, Math.PI * 2);
        context.fillStyle = particle.tone > 0.72
          ? `rgba(133, 226, 255, ${0.35 + pulse * 0.35})`
          : `rgba(74, 143, 255, ${0.22 + pulse * 0.4})`;
        context.shadowColor = particle.tone > 0.72 ? '#78e8ff' : '#4a8fff';
        context.shadowBlur = 8 + particle.radius * 5;
        context.fill();
        context.shadowBlur = 0;

        if (pointer.active) {
          const distance = Math.hypot(pointer.x - x, pointer.y - y);
          if (distance < 145) {
            context.beginPath();
            context.moveTo(x, y);
            context.lineTo(pointer.x, pointer.y);
            context.strokeStyle = `rgba(91, 225, 214, ${(1 - distance / 145) * 0.18})`;
            context.lineWidth = 0.8;
            context.stroke();
          }
        }
      });

      for (let index = ripples.length - 1; index >= 0; index -= 1) {
        const ripple = ripples[index];
        ripple.life += 0.025;
        context.beginPath();
        context.arc(ripple.x, ripple.y, 24 + ripple.life * 145, 0, Math.PI * 2);
        context.strokeStyle = `rgba(88, 231, 218, ${Math.max(0, 0.28 - ripple.life * 0.28)})`;
        context.lineWidth = 1.2;
        context.stroke();
        if (ripple.life >= 1) ripples.splice(index, 1);
      }

      if (!reducedMotion) animationId = window.requestAnimationFrame(render);
    };

    resize();
    render();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', movePointer, { passive: true });
    document.documentElement.addEventListener('pointerleave', leavePointer);
    window.addEventListener('pointerdown', addRipple, { passive: true });

    return () => {
      window.cancelAnimationFrame(animationId);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', movePointer);
      document.documentElement.removeEventListener('pointerleave', leavePointer);
      window.removeEventListener('pointerdown', addRipple);
    };
  }, []);

  return <canvas ref={canvasRef} className="interactive-background" aria-hidden="true" />;
}

(() => {
  'use strict';

  const root = document.documentElement;
  const shell = document.querySelector('.site-shell');
  if (!shell) return;
  const reducedPreference = matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const preferenceKey = 'lungsight.website.motion';
  let userPaused = false;
  try { userPaused = localStorage.getItem(preferenceKey) === 'paused'; } catch { /* Storage is optional. */ }
  const reduced = () => reducedPreference.matches || userPaused;
  const running = () => !reduced() && !document.hidden;
  const animations = new Set();

  const animate = (element, frames, options) => {
    if (!element?.animate || !running()) return;
    const animation = element.animate(frames, options);
    animations.add(animation);
    const finished = () => animations.delete(animation);
    animation.addEventListener('finish', finished, { once: true });
    animation.addEventListener('cancel', finished, { once: true });
    return animation;
  };

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'motion-toggle';
  toggle.setAttribute('aria-label', '页面动态效果');
  toggle.innerHTML = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M2 10h3l2-5 4 10 2-5h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg><span></span>';
  shell.append(toggle);

  const revealElements = [...shell.querySelectorAll('.reveal')];
  const show = element => { element.dataset.reveal = 'visible'; };
  let revealObserver;
  const prepareReveals = () => {
    revealObserver?.disconnect();
    if (reduced() || !('IntersectionObserver' in window)) {
      revealElements.forEach(show);
      return;
    }
    revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        show(entry.target);
        revealObserver.unobserve(entry.target);
      });
    }, { threshold: 0, rootMargin: '0px 0px -20px 0px' });
    revealElements.forEach(element => {
      // Never hide content already read, or content in the initial viewport.
      if (element.dataset.reveal === 'visible' || element.getBoundingClientRect().top < innerHeight - 20) {
        show(element);
        return;
      }
      const siblings = [...element.parentElement.children].filter(node => node.classList.contains('reveal'));
      element.style.setProperty('--reveal-delay', `${Math.min(siblings.indexOf(element) * 65, 195)}ms`);
      element.dataset.reveal = 'pending';
      revealObserver.observe(element);
    });
  };
  shell.addEventListener('focusin', event => {
    // Keyboard navigation must never land on an invisible link.
    let parent = event.target.closest('[data-reveal="pending"]');
    while (parent) {
      show(parent);
      revealObserver?.unobserve(parent);
      parent = parent.parentElement.closest('[data-reveal="pending"]');
    }
  });

  const nav = shell.querySelector('.nav-wrap');
  const progress = shell.querySelector('.page-progress');
  if (progress) progress.style.width = '100%';
  const navLinks = [...shell.querySelectorAll('.nav-links a[href^="#"], .nav-more-panel a[href^="#"]')];
  const sections = [...new Set(navLinks.map(link => document.getElementById(link.hash.slice(1))).filter(Boolean))];
  let scrollFrame = 0;
  let activeSection = '';
  const updateScroll = () => {
    scrollFrame = 0;
    const total = root.scrollHeight - innerHeight;
    if (progress) progress.style.transform = `scaleX(${total > 0 ? Math.max(0, Math.min(1, scrollY / total)) : 0})`;
    nav?.classList.toggle('is-scrolled', scrollY > 40);
    let next = '';
    let nearest = -Infinity;
    sections.forEach(section => {
      const top = section.getBoundingClientRect().top;
      if (top <= innerHeight * .3 && top > nearest) { nearest = top; next = section.id; }
    });
    if (next !== activeSection) {
      activeSection = next;
      navLinks.forEach(link => {
        if (link.hash === `#${next}`) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }
  };
  const scheduleScroll = () => {
    if (!scrollFrame && !document.hidden) scrollFrame = requestAnimationFrame(updateScroll);
  };
  addEventListener('scroll', scheduleScroll, { passive: true });
  addEventListener('resize', scheduleScroll, { passive: true });
  addEventListener('load', scheduleScroll, { once: true });
  if ('ResizeObserver' in window) new ResizeObserver(scheduleScroll).observe(shell);

  const pointerResets = [];
  const bindPointer = (element, update, reset) => {
    if (!element) return;
    let frame = 0;
    let position;
    const stop = () => { cancelAnimationFrame(frame); frame = 0; reset(); };
    pointerResets.push(stop);
    element.addEventListener('pointermove', event => {
      if (!running() || !finePointer.matches || event.pointerType === 'touch') return;
      position = { x: event.clientX, y: event.clientY };
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!running() || !finePointer.matches) return;
        const rect = element.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const x = Math.max(-1, Math.min(1, (position.x - rect.left) / rect.width * 2 - 1));
        const y = Math.max(-1, Math.min(1, (position.y - rect.top) / rect.height * 2 - 1));
        update(x, y);
      });
    }, { passive: true });
    element.addEventListener('pointerleave', stop);
    element.addEventListener('pointercancel', stop);
  };
  const hero = shell.querySelector('.hero-visual');
  bindPointer(hero, (x, y) => {
    hero.style.setProperty('--hero-rx', `${-y * 2}deg`);
    hero.style.setProperty('--hero-ry', `${x * 2.5}deg`);
  }, () => {
    hero.style.removeProperty('--hero-rx');
    hero.style.removeProperty('--hero-ry');
  });
  const graph = shell.querySelector('.tech-graph-canvas');
  const nodes = [...(graph?.querySelectorAll('.tech-node-wrap') || [])];
  bindPointer(graph, (x, y) => {
    graph.style.setProperty('--center-x', `${x * 6}px`);
    graph.style.setProperty('--center-y', `${y * 5}px`);
    graph.style.setProperty('--light-x', `${(x + 1) * 50}%`);
    graph.style.setProperty('--light-y', `${(y + 1) * 50}%`);
    nodes.forEach((node, index) => {
      const depth = 1.5 + index % 4;
      node.style.setProperty('--node-x', `${x * depth}px`);
      node.style.setProperty('--node-y', `${y * depth}px`);
    });
  }, () => {
    graph.style.setProperty('--center-x', '0px');
    graph.style.setProperty('--center-y', '0px');
    graph.style.setProperty('--light-x', '50%');
    graph.style.setProperty('--light-y', '50%');
    nodes.forEach(node => {
      node.style.setProperty('--node-x', '0px');
      node.style.setProperty('--node-y', '0px');
    });
  });

  const preview = shell.querySelector('.demo-image img');
  let previewAnimation;
  preview?.addEventListener('load', () => {
    previewAnimation?.cancel();
    previewAnimation = animate(preview, [{ opacity: .35 }, { opacity: 1 }], { duration: 280, easing: 'ease-out' });
  });

  // A bounded 30 fps background, with fewer particles on touch screens.
  const canvas = shell.querySelector('.interactive-background');
  const context = canvas?.getContext('2d');
  const pointer = { x: 0, y: 0, active: false };
  let width = 0;
  let height = 0;
  let particles = [];
  let canvasFrame = 0;
  let lastFrame = 0;
  let clock = 0;
  const draw = delta => {
    if (!context) return;
    context.clearRect(0, 0, width, height);
    clock += delta * .00025;
    const step = delta / 33.33;
    particles.forEach(point => {
      point.x += point.vx * step;
      point.y += point.vy * step;
      if (point.x < -10) point.x = width + 10;
      if (point.x > width + 10) point.x = -10;
      if (point.y < -10) point.y = height + 10;
      if (point.y > height + 10) point.y = -10;
    });
    if (finePointer.matches) {
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const first = particles[i], second = particles[j];
          const distance = Math.hypot(first.x - second.x, first.y - second.y);
          if (distance >= 115) continue;
          context.beginPath();
          context.moveTo(first.x, first.y);
          context.lineTo(second.x, second.y);
          context.strokeStyle = `rgba(98,188,221,${(1 - distance / 115) * .11})`;
          context.lineWidth = .65;
          context.stroke();
        }
      }
    }
    particles.forEach(point => {
      const pulse = reduced() ? .7 : .65 + Math.sin(clock + point.phase) * .18;
      context.beginPath();
      context.arc(point.x, point.y, point.radius, 0, Math.PI * 2);
      context.fillStyle = `rgba(112,218,232,${pulse * .65})`;
      context.fill();
    });
    if (pointer.active && running() && finePointer.matches) {
      const glow = context.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, 240);
      glow.addColorStop(0, 'rgba(78,210,220,.07)');
      glow.addColorStop(1, 'rgba(78,210,220,0)');
      context.fillStyle = glow;
      context.fillRect(pointer.x - 240, pointer.y - 240, 480, 480);
    }
  };
  const tick = timestamp => {
    canvasFrame = 0;
    if (!running() || !context) return;
    if (timestamp - lastFrame >= 1000 / 30) {
      draw(lastFrame ? Math.min(64, timestamp - lastFrame) : 0);
      lastFrame = timestamp;
    }
    canvasFrame = requestAnimationFrame(tick);
  };
  const startCanvas = () => {
    if (context && running() && !canvasFrame) {
      lastFrame = 0;
      canvasFrame = requestAnimationFrame(tick);
    }
  };
  const resizeCanvas = () => {
    if (!context) return;
    width = innerWidth;
    height = innerHeight;
    const density = Math.min(devicePixelRatio || 1, finePointer.matches ? 1.4 : 1);
    canvas.width = Math.round(width * density);
    canvas.height = Math.round(height * density);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(density, 0, 0, density, 0, 0);
    const count = reduced() ? 20 : finePointer.matches ? Math.min(64, Math.max(30, Math.round(width * height / 28000))) : 22;
    particles = Array.from({ length: count }, () => ({
      x: Math.random() * width, y: Math.random() * height,
      vx: (Math.random() - .5) * .26, vy: (Math.random() - .5) * .2,
      radius: .65 + Math.random() * 1.6, phase: Math.random() * Math.PI * 2,
    }));
    draw(0);
    startCanvas();
  };
  addEventListener('resize', resizeCanvas, { passive: true });
  addEventListener('pointermove', event => {
    if (!running() || !finePointer.matches || event.pointerType === 'touch') return;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    pointer.active = true;
  }, { passive: true });
  root.addEventListener('pointerleave', () => { pointer.active = false; });

  const applyPreference = () => {
    root.dataset.motion = reduced() ? 'reduced' : 'full';
    toggle.disabled = reducedPreference.matches;
    toggle.setAttribute('aria-pressed', String(!reduced()));
    toggle.querySelector('span').textContent = reducedPreference.matches ? '系统已减少动效' : userPaused ? '动效已暂停' : '动效已开启';
    toggle.title = reducedPreference.matches ? '遵循系统的减少动态效果设置' : userPaused ? '开启页面动态效果' : '暂停页面动态效果';
    animations.forEach(animation => animation.cancel());
    pointerResets.forEach(reset => reset());
    pointer.active = false;
    cancelAnimationFrame(canvasFrame);
    canvasFrame = 0;
    prepareReveals();
    resizeCanvas();
    dispatchEvent(new CustomEvent('lungsight:motionchange'));
  };
  toggle.addEventListener('click', () => {
    userPaused = !userPaused;
    try { localStorage.setItem(preferenceKey, userPaused ? 'paused' : 'full'); } catch { /* Storage is optional. */ }
    applyPreference();
  });
  reducedPreference.addEventListener('change', applyPreference);
  finePointer.addEventListener('change', applyPreference);
  document.addEventListener('visibilitychange', () => {
    root.dataset.pageHidden = String(document.hidden);
    if (document.hidden) {
      cancelAnimationFrame(canvasFrame);
      cancelAnimationFrame(scrollFrame);
      canvasFrame = 0;
      scrollFrame = 0;
      animations.forEach(animation => animation.pause());
      pointerResets.forEach(reset => reset());
      pointer.active = false;
    } else {
      animations.forEach(animation => { if (!reduced()) animation.play(); });
      startCanvas();
      scheduleScroll();
    }
  });
  root.dataset.pageHidden = String(document.hidden);
  applyPreference();
  updateScroll();
  [...shell.querySelectorAll('.hero-copy > *')].forEach((element, index) => {
    animate(element, [{ opacity: 0, transform: 'translateY(16px)' }, { opacity: 1, transform: 'none' }], {
      duration: 650, delay: Math.min(index * 75, 375), easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards',
    });
  });
})();

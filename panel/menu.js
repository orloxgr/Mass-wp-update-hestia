// Managed by mass-wp-update-hestia
(() => {
  'use strict';
  const addon = { id: 'mass-wp-update', title: 'Mass WP Update', href: '/plugins/mass-wp-update/' };

  function register() {
    const header = document.querySelector('.app-header .top-bar-right');
    if (!header) return;
    let menu = document.getElementById('hestia-addons-menu');
    if (!menu) {
      const style = document.createElement('style');
      style.textContent = `
        #hestia-addons-menu { position:relative; display:flex; }
        #hestia-addons-menu > button { gap:8px; height:100%; white-space:nowrap; }
        #hestia-addons-list { position:absolute; top:100%; right:0; z-index:50;
          width:210px; max-width:calc(100vw - 24px); margin:0; padding:6px;
          list-style:none; background:var(--color-background,#fff);
          border:1px solid var(--alert-border-color,#ddd); border-radius:0 0 6px 6px;
          box-shadow:0 5px 18px #0004; }
        #hestia-addons-list[hidden] { display:none !important; }
        #hestia-addons-list a { display:block; padding:10px 14px; border-radius:3px;
          color:var(--color-text,#333); font-size:14px; text-decoration:none; }
        #hestia-addons-list a:hover, #hestia-addons-list a:focus-visible {
          color:var(--color-text-link,#006b9f); background:var(--top-bar-background,#f3f3f3); }
      `;
      document.head.append(style);
      menu = document.createElement('div');
      menu.id = 'hestia-addons-menu';
      menu.dataset.hestiaAddonsFocusSafe = '1';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'top-bar-menu-link';
      button.setAttribute('aria-expanded', 'false');
      button.setAttribute('aria-controls', 'hestia-addons-list');
      const icon = document.createElement('i');
      icon.className = 'fas fa-puzzle-piece';
      icon.setAttribute('aria-hidden', 'true');
      button.append(icon, document.createTextNode('Plugins'));
      const list = document.createElement('ul');
      list.id = 'hestia-addons-list';
      list.hidden = true;
      menu.append(button, list);
      header.prepend(menu);

      function close(focus = false) {
        list.hidden = true;
        button.setAttribute('aria-expanded', 'false');
        if (focus) button.focus();
      }
      function open() {
        list.hidden = false;
        button.setAttribute('aria-expanded', 'true');
      }
      button.addEventListener('click', () => list.hidden ? open() : close());
      button.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          open();
          const links = list.querySelectorAll('a');
          (event.key === 'ArrowDown' ? links[0] : links[links.length - 1])?.focus();
        }
      });
      list.addEventListener('keydown', (event) => {
        const links = Array.from(list.querySelectorAll('a'));
        const direction = event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0;
        if (direction && links.length) {
          event.preventDefault();
          const index = links.indexOf(document.activeElement);
          links[(index + direction + links.length) % links.length].focus();
        }
      });
      document.addEventListener('click', (event) => {
        if (!menu.contains(event.target)) close();
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !list.hidden) {
          event.preventDefault();
          close(true);
        }
      });
      menu.addEventListener('focusout', (event) => {
        if (event.relatedTarget && !menu.contains(event.relatedTarget)) close();
      });
    } else if (!menu.dataset.hestiaAddonsFocusSafe) {
      // Another addon may have created an older shared menu. Keep its focusout
      // listener from hiding a link between pointer-down and click.
      menu.addEventListener('focusout', (event) => {
        if (event.relatedTarget && menu.contains(event.relatedTarget)) {
          event.stopImmediatePropagation();
        }
      }, true);
      menu.dataset.hestiaAddonsFocusSafe = '1';
    }
    const list = menu.querySelector('#hestia-addons-list');
    if (!list || list.querySelector(`[data-hestia-addon="${addon.id}"]`)) return;
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.dataset.hestiaAddon = addon.id;
    link.href = addon.href;
    link.textContent = addon.title;
    item.append(link);
    list.append(item);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', register, { once: true });
  } else {
    register();
  }
})();

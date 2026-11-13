// Do React Bits (registro @react-bits, StaggeredMenu-TS-CSS). Adaptado ao painel:
// itens com Link do react-router (sem recarregar a página), logo e rodapé como
// nós, textos em português, Esc fecha, painel inerte fechado e sem animação com
// redução de movimento.
'use client';

import React, { type CSSProperties, type ReactNode, useCallback, useRef, useState } from 'react';
import { Link } from 'react-router';
import './StaggeredMenu.css';

export interface StaggeredMenuItem {
  label: string;
  ariaLabel: string;
  link: string;
  ativo?: boolean;
}

export interface StaggeredMenuSocialItem {
  label: string;
  link: string;
}

export interface StaggeredMenuProps {
  position?: 'left' | 'right';
  colors?: string[];
  items?: StaggeredMenuItem[];
  socialItems?: StaggeredMenuSocialItem[];
  displaySocials?: boolean;
  displayItemNumbering?: boolean;
  className?: string;
  logoUrl?: string;
  menuButtonColor?: string;
  openMenuButtonColor?: string;
  accentColor?: string;
  changeMenuColorOnOpen?: boolean;
  closeOnClickAway?: boolean;
  onMenuOpen?: () => void;
  onMenuClose?: () => void;
  isFixed?: boolean;
  logo?: ReactNode;
  rodape?: ReactNode;
  rodapeTitulo?: string;
}

export const StaggeredMenu: React.FC<StaggeredMenuProps> = ({
  position = 'right',
  colors = ['#B497CF', '#5227FF'],
  items = [],
  socialItems = [],
  displaySocials = true,
  displayItemNumbering = true,
  className,
  logoUrl = '/src/assets/logos/reactbits-gh-white.svg',
  menuButtonColor = '#fff',
  openMenuButtonColor = '#fff',
  changeMenuColorOnOpen = true,
  accentColor = '#5227FF',
  isFixed = false,
  closeOnClickAway = true,
  onMenuOpen,
  onMenuClose,
  logo,
  rodape,
  rodapeTitulo = 'Conta'
}: StaggeredMenuProps) => {
  // A coreografia (painel, camadas, itens em cascata, ícone e rótulo do botão)
  // é toda CSS, presa ao `data-open` do invólucro: ver StaggeredMenu.css.
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const toggleBtnRef = useRef<HTMLButtonElement | null>(null);

  const toggleMenu = useCallback(() => {
    setOpen(!open);
    if (open) onMenuClose?.();
    else onMenuOpen?.();
  }, [open, onMenuOpen, onMenuClose]);

  const closeMenu = useCallback(() => {
    if (!open) return;
    setOpen(false);
    onMenuClose?.();
  }, [open, onMenuClose]);

  React.useEffect(() => {
    if (!closeOnClickAway || !open) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(event.target as Node) &&
        toggleBtnRef.current &&
        !toggleBtnRef.current.contains(event.target as Node)
      ) {
        closeMenu();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [closeOnClickAway, open, closeMenu]);

  React.useEffect(() => {
    if (!open) return;
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      closeMenu();
      toggleBtnRef.current?.focus();
    };
    document.addEventListener('keydown', aoTeclar);
    // Sem rolar: o item ainda está fora da tela, deslizando; rolar o invólucro
    // arrastava o topo junto e quebrava a abertura.
    panelRef.current?.querySelector<HTMLElement>('.sm-panel-item')?.focus({ preventScroll: true });
    return () => document.removeEventListener('keydown', aoTeclar);
  }, [open, closeMenu]);

  return (
    <div
      className={(className ? className + ' ' : '') + 'staggered-menu-wrapper' + (isFixed ? ' fixed-wrapper' : '')}
      style={accentColor ? ({ '--sm-accent': accentColor } as CSSProperties) : undefined}
      data-position={position}
      data-open={open || undefined}
    >
      <div className="sm-prelayers" aria-hidden="true">
        {(() => {
          const raw = colors && colors.length ? colors.slice(0, 4) : ['#1e1e22', '#35353c'];
          let arr = [...raw];
          if (arr.length >= 3) {
            const mid = Math.floor(arr.length / 2);
            arr.splice(mid, 1);
          }
          return arr.map((c, i) => (
            <div key={i} className="sm-prelayer" style={{ background: c, '--i': i } as CSSProperties} />
          ));
        })()}
      </div>
      <header className="staggered-menu-header">
        <div className="sm-logo">
          {logo ?? (
            <img src={logoUrl} alt="Logo" className="sm-logo-img" draggable={false} width={110} height={24} />
          )}
        </div>
        <button
          ref={toggleBtnRef}
          className="sm-toggle"
          aria-label={open ? 'Fechar menu' : 'Abrir menu'}
          aria-expanded={open}
          aria-controls="staggered-menu-panel"
          onClick={toggleMenu}
          type="button"
          style={{ color: open && changeMenuColorOnOpen ? openMenuButtonColor : menuButtonColor }}
        >
          <span className="sm-toggle-textWrap" aria-hidden="true">
            <span className="sm-toggle-textInner">
              <span className="sm-toggle-line">Menu</span>
              <span className="sm-toggle-line">Fechar</span>
            </span>
          </span>
          <span className="sm-icon" aria-hidden="true">
            <span className="sm-icon-line" />
            <span className="sm-icon-line sm-icon-line-v" />
          </span>
        </button>
      </header>

      <aside
        id="staggered-menu-panel"
        ref={panelRef}
        className="staggered-menu-panel"
        aria-label="Menu"
        aria-hidden={!open}
        inert={!open || undefined}
      >
        <div className="sm-panel-inner">
          <ul className="sm-panel-list" role="list" data-numbering={displayItemNumbering || undefined}>
            {items && items.length ? (
              items.map((it, idx) => (
                <li className="sm-panel-itemWrap" key={it.label + idx} style={{ '--i': idx } as CSSProperties}>
                  <Link
                    className="sm-panel-item"
                    to={it.link}
                    aria-label={it.ariaLabel}
                    aria-current={it.ativo ? 'page' : undefined}
                    data-index={idx + 1}
                    onClick={closeMenu}
                  >
                    <span className="sm-panel-itemLabel">{it.label}</span>
                  </Link>
                </li>
              ))
            ) : (
              <li className="sm-panel-itemWrap" aria-hidden="true">
                <span className="sm-panel-item">
                  <span className="sm-panel-itemLabel">Sem itens</span>
                </span>
              </li>
            )}
          </ul>
          {rodape && (
            <div className="sm-socials">
              <h3 className="sm-socials-title">{rodapeTitulo}</h3>
              {rodape}
            </div>
          )}
          {displaySocials && socialItems && socialItems.length > 0 && (
            <div className="sm-socials" aria-label="Social links">
              <h3 className="sm-socials-title">Socials</h3>
              <ul className="sm-socials-list" role="list">
                {socialItems.map((s, i) => (
                  <li key={s.label + i} className="sm-socials-item">
                    <a href={s.link} target="_blank" rel="noopener noreferrer" className="sm-socials-link">
                      {s.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
};

export default StaggeredMenu;

import type React from "react";
// Types for the React Bits components (they ship as JavaScript).
import type { CSSProperties, FC } from "react";

export interface GrainientProps {
  colors?: string[]; type?: "linear" | "radial"; angle?: number; bands?: number; softness?: number; flow?: number;
  scale?: number; speed?: number; silk?: number; grainAmount?: number; grainSize?: number; grainAnimated?: boolean;
  contrast?: number; saturation?: number; variation?: number; interactive?: boolean; stir?: number;
  clickSwirl?: boolean; intro?: boolean; lightMode?: boolean; dpr?: number; className?: string; style?: CSSProperties;
}

export interface TechTextProps {
  text?: string; fontFamily?: string; fontWeight?: number; fontSize?: number; letterSpacing?: number;
  align?: "left" | "center" | "right"; color?: string; accentColor?: string; reveal?: "area" | "letter" | "off";
  reach?: number; softness?: number; dashLength?: number; dashGap?: number; lineStyle?: "dashed" | "solid";
  strokeWidth?: number; specks?: number; selection?: boolean; labels?: boolean; draggable?: boolean; bounce?: number;
  clickKick?: boolean; intro?: "none" | "type" | "assemble" | "metrics"; introDuration?: number; guides?: boolean;
  sweep?: boolean; speed?: number; ignoreReducedMotion?: boolean; className?: string; style?: CSSProperties;
}
export interface HalftoneRevealProps {
  src: string; revealSrc?: string; fit?: "contain" | "cover";
  shape?: "dot" | "ellipse" | "square" | "diamond" | "line" | "cross"; cellSize?: number; angle?: number;
  paperColor?: string; revealRadius?: number; softness?: number; linger?: number; reverse?: boolean; wander?: boolean;
  clickBurst?: boolean; intro?: boolean; ignoreReducedMotion?: boolean; className?: string; style?: CSSProperties;
}
export interface FlowingMenuItem { text: string; link?: string; image?: string; marquee?: string; meta?: string }
export interface FlowingMenuProps {
  items?: FlowingMenuItem[]; speed?: number; direction?: "left" | "right" | "alternate"; followCursor?: number;
  duration?: number; stretch?: number; magnet?: number; bandInset?: number; carryContent?: boolean; bandRadius?: number;
  textColor?: string; bgColor?: string; marqueeBgColor?: string; marqueeTextColor?: string; borderColor?: string;
  dividers?: boolean; dimInactive?: boolean; align?: "center" | "left"; showIndex?: boolean; showArrow?: boolean;
  imageShape?: "pill" | "rounded" | "circle"; intro?: boolean; activeIndex?: number;
  onItemClick?: (item: FlowingMenuItem, index: number, event: React.MouseEvent) => void; ariaLabel?: string;
  ignoreReducedMotion?: boolean;
  className?: string; style?: CSSProperties;
}
export interface SpiralItem {
  src: string; alt?: string; href?: string; target?: string; label?: string; id?: string; content?: React.ReactNode;
}
export interface InfiniteSpiralProps {
  items?: (string | SpiralItem)[]; speed?: number; direction?: "up" | "down";
  animationMode?: "auto" | "drag" | "scroll" | "all"; radius?: number; cardWidth?: number; cardHeight?: number;
  verticalSpacing?: number; perspective?: number; cardsPerTurn?: number; rotation?: number; cardTilt?: number;
  cardRadius?: number; centerScale?: number; edgeFade?: number; edgeBlur?: number; pauseOnHover?: boolean;
  imageFit?: "cover" | "contain"; grayscale?: number; wheel?: boolean; ignoreReducedMotion?: boolean;
  className?: string;
}

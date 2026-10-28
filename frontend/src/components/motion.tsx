import type { ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";

const EASE = [0.16, 1, 0.3, 1] as const;
const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");

/**
 * Cross-fades content when `k` changes: the outgoing version fades/blurs away while the incoming
 * one fades in on top of it (no empty frame), and the surrounding box eases to the new size.
 */
export function Swap({ k, children, className, inline = false, y = 6 }: { k: string | number; children: ReactNode; className?: string; inline?: boolean; y?: number }) {
  const Box = inline ? motion.span : motion.div;
  const Item = inline ? motion.span : motion.div;
  return (
    <Box layout="size" transition={{ layout: { duration: 0.35, ease: EASE } }} className={cx("relative", inline ? "inline-block" : "block", className)}>
      <AnimatePresence mode="popLayout" initial={false}>
        <Item
          key={k}
          className={inline ? "inline-block" : "block"}
          initial={{ opacity: 0, y, filter: "blur(3px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          exit={{ opacity: 0, y: -y, filter: "blur(3px)" }}
          transition={{ duration: 0.38, ease: EASE }}
        >
          {children}
        </Item>
      </AnimatePresence>
    </Box>
  );
}

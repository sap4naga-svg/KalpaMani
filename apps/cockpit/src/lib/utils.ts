import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** The shadcn/ui class-merge helper. See NOTICE.md for third-party attribution. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

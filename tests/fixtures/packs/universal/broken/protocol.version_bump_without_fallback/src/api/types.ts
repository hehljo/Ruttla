import { z } from "zod";
export enum Kind { Text, Image }
export const S = z.enum(["a"]);

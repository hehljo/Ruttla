import { z } from "zod";
export enum Kind { Text, Image, Unknown }
export const S = z.enum(["a"]);

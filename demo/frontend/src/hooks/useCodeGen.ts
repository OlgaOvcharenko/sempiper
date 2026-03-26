import { useMutation } from "@tanstack/react-query";
import { generateCode, type GenerateRequest, type GenerateResponse } from "../api/client";

export function useCodeGen() {
  return useMutation<GenerateResponse, Error, GenerateRequest>({
    mutationFn: generateCode,
  });
}

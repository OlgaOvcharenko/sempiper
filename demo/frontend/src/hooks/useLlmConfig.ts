import { useState, useCallback } from "react";

export interface UseLlmConfigReturn {
  llmName: string;
  temperature: string;
  temperatureError: boolean;
  temperatureShake: boolean;
  setLlmName: (name: string) => void;
  handleTemperatureChange: (value: string) => void;
  /** Pure validation — does not mutate state. */
  validateTemperature: (value: string) => boolean;
  /** Triggers the error highlight + shake animation without changing the temperature value. */
  markTemperatureInvalid: () => void;
}

export function useLlmConfig(opts?: {
  initialLlmName?: string;
  initialTemperature?: string;
}): UseLlmConfigReturn {
  const [llmName, setLlmName] = useState(
    opts?.initialLlmName ?? "gemini/gemini-2.5-flash-lite"
  );
  const [temperature, setTemperature] = useState(opts?.initialTemperature ?? "0.0");
  const [temperatureError, setTemperatureError] = useState(false);
  const [temperatureShake, setTemperatureShake] = useState(false);

  const validateTemperature = useCallback((value: string): boolean => {
    if (value.trim() === "") return false;
    const num = parseFloat(value);
    if (isNaN(num)) return false;
    // Both OpenAI and Gemini support temperature range 0 to 2
    return num >= 0 && num <= 2;
  }, []);

  const markTemperatureInvalid = useCallback(() => {
    setTemperatureError(true);
    setTemperatureShake(true);
    setTimeout(() => setTemperatureShake(false), 820);
  }, []);

  const handleTemperatureChange = useCallback(
    (value: string) => {
      setTemperature(value);
      const isInvalid = value.trim() !== "" && !validateTemperature(value);
      if (isInvalid) {
        markTemperatureInvalid();
      } else {
        setTemperatureError(false);
        setTemperatureShake(false);
      }
    },
    [validateTemperature, markTemperatureInvalid]
  );

  return {
    llmName,
    temperature,
    temperatureError,
    temperatureShake,
    setLlmName,
    handleTemperatureChange,
    validateTemperature,
    markTemperatureInvalid,
  };
}

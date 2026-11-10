import { useState, useEffect, useRef, useCallback } from 'react';

declare global {
  interface Window {
    webgazer: any;
  }
}

interface EyeTrackingState {
  isLoading: boolean;
  isActive: boolean;
  isCalibrating: boolean;
  error: string | null;
  gazeY: number | null;
}

export function useEyeTracking(containerRef: React.RefObject<HTMLElement>) {
  const [state, setState] = useState<EyeTrackingState>({
    isLoading: false,
    isActive: false,
    isCalibrating: false,
    error: null,
    gazeY: null,
  });
  
  const gazeListenerRef = useRef<((data: any, elapsedTime: number) => void) | null>(null);
  const scrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastScrollRef = useRef<number>(0);
  const gazeHistoryRef = useRef<{y: number, timestamp: number}[]>([]);

  // Load WebGazer script
  const loadWebGazer = useCallback(async () => {
    if (window.webgazer) return true;

    return new Promise<boolean>((resolve) => {
      const script = document.createElement('script');
      script.src = 'https://webgazer.cs.brown.edu/webgazer.js';
      script.async = true;
      script.onload = () => {
        console.log('WebGazer loaded');
        resolve(true);
      };
      script.onerror = () => {
        console.error('Failed to load WebGazer');
        resolve(false);
      };
      document.head.appendChild(script);
    });
  }, []);

  // Start eye tracking
  const startTracking = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      const loaded = await loadWebGazer();
      if (!loaded || !window.webgazer) {
        throw new Error('Failed to load eye tracking library');
      }

      // Configure webgazer
      window.webgazer
        .setRegression('ridge')
        .setTracker('TFFacemesh')
        .showVideoPreview(true)
        .showPredictionPoints(true)
        .applyKalmanFilter(true);

      // Start and begin calibration
      await window.webgazer.begin();
      
      setState(prev => ({ 
        ...prev, 
        isLoading: false, 
        isActive: true,
        isCalibrating: true 
      }));

      // Auto-stop calibration after 15 seconds
      setTimeout(() => {
        // Hide video and prediction points after calibration
        if (window.webgazer) {
          window.webgazer.showVideoPreview(false);
          window.webgazer.showPredictionPoints(false);
        }
        setState(prev => ({ ...prev, isCalibrating: false }));
      }, 15000);

    } catch (err: any) {
      console.error('Eye tracking error:', err);
      setState(prev => ({ 
        ...prev, 
        isLoading: false, 
        error: err.message || 'Failed to start eye tracking'
      }));
    }
  }, [loadWebGazer]);

  // End calibration early
  const endCalibration = useCallback(() => {
    if (window.webgazer) {
      window.webgazer.showVideoPreview(false);
      window.webgazer.showPredictionPoints(false);
    }
    setState(prev => ({ ...prev, isCalibrating: false }));
  }, []);

  // Stop tracking
  const stopTracking = useCallback(() => {
    if (window.webgazer) {
      window.webgazer.end();
      window.webgazer.showVideoPreview(false);
      window.webgazer.showPredictionPoints(false);
    }
    setState({
      isLoading: false,
      isActive: false,
      isCalibrating: false,
      error: null,
      gazeY: null,
    });
  }, []);

  // Handle auto-scroll based on gaze position
  useEffect(() => {
    if (!state.isActive || state.isCalibrating || !window.webgazer) return;

    const handleGaze = (data: any, elapsedTime: number) => {
      if (!data) return;

      const viewportHeight = window.innerHeight;
      const gazeY = data.y;
      const now = Date.now();
      
      // Add to gaze history
      gazeHistoryRef.current.push({ y: gazeY, timestamp: now });
      
      // Keep only last 10 seconds of data
      const tenSecondsAgo = now - 10000;
      gazeHistoryRef.current = gazeHistoryRef.current.filter(g => g.timestamp > tenSecondsAgo);
      
      // Need at least 2 seconds of data before scrolling
      if (gazeHistoryRef.current.length < 10) return;
      
      // Calculate average Y position
      const avgY = gazeHistoryRef.current.reduce((sum, g) => sum + g.y, 0) / gazeHistoryRef.current.length;
      
      setState(prev => ({ ...prev, gazeY: avgY }));

      // Throttle scrolling - only scroll every 2 seconds
      if (now - lastScrollRef.current < 2000) return;

      // If average gaze is in bottom 15% of screen, scroll down gently
      if (avgY > viewportHeight * 0.85) {
        window.scrollBy({ top: 40, behavior: 'smooth' });
        lastScrollRef.current = now;
        // Clear some history after scroll to prevent continuous scrolling
        gazeHistoryRef.current = gazeHistoryRef.current.slice(-5);
      } 
      // If average gaze is in top 10%, scroll up gently
      else if (avgY < viewportHeight * 0.1 && window.scrollY > 0) {
        window.scrollBy({ top: -40, behavior: 'smooth' });
        lastScrollRef.current = now;
        gazeHistoryRef.current = gazeHistoryRef.current.slice(-5);
      }
    };

    gazeListenerRef.current = handleGaze;
    window.webgazer.setGazeListener(handleGaze);

    return () => {
      if (window.webgazer) {
        window.webgazer.clearGazeListener();
      }
    };
  }, [state.isActive, state.isCalibrating]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopTracking();
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };
  }, [stopTracking]);

  return {
    ...state,
    startTracking,
    stopTracking,
    endCalibration,
  };
}

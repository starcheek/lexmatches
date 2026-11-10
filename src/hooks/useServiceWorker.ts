import { useEffect, useState, useCallback } from 'react';
import { toast } from 'sonner';

interface CacheStatus {
  isSupported: boolean;
  isRegistered: boolean;
  isOnline: boolean;
}

export const useServiceWorker = () => {
  const [status, setStatus] = useState<CacheStatus>({
    isSupported: 'serviceWorker' in navigator,
    isRegistered: false,
    isOnline: navigator.onLine,
  });

  useEffect(() => {
    if (!status.isSupported) return;

    // Register service worker
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        setStatus((prev) => ({ ...prev, isRegistered: true }));
        console.log('Service Worker registered:', registration.scope);
      })
      .catch((error) => {
        console.error('Service Worker registration failed:', error);
      });

    // Listen for online/offline events
    const handleOnline = () => {
      setStatus((prev) => ({ ...prev, isOnline: true }));
      toast.success('Back online');
    };

    const handleOffline = () => {
      setStatus((prev) => ({ ...prev, isOnline: false }));
      toast.info('You are offline. Reading from cache.');
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [status.isSupported]);

  // Cache specific pages for offline reading
  const cachePages = useCallback((pages: any[]) => {
    if (!status.isSupported || !status.isRegistered) return;

    navigator.serviceWorker.controller?.postMessage({
      type: 'CACHE_PAGES',
      pages,
    });
  }, [status.isSupported, status.isRegistered]);

  // Clear all caches
  const clearCache = useCallback(async () => {
    if (!status.isSupported) return;

    navigator.serviceWorker.controller?.postMessage({
      type: 'CLEAR_CACHE',
    });
    toast.success('Cache cleared');
  }, [status.isSupported]);

  return {
    ...status,
    cachePages,
    clearCache,
  };
};

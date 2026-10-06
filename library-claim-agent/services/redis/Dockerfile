FROM redis:7-alpine
CMD ["redis-server", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru", "--save", ""]

#!/bin/bash

# HarvestMind Pre-flight Doctor
# Checks for port conflicts and common setup issues

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}🔍 Running HarvestMind Pre-flight Check...${NC}"

CHECK_PORTS=(3000 8000 3002)
CONFLICTS=0

# 1. Check host processes
for PORT in "${CHECK_PORTS[@]}"
do
    PID=$(lsof -ti :$PORT)
    if [ ! -z "$PID" ]; then
        PROCESS_NAME=$(ps -p $PID -o comm=)
        echo -e "${RED}❌ Port $PORT is in use by host process: $PROCESS_NAME (PID: $PID)${NC}"
        CONFLICTS=$((CONFLICTS+1))
    fi
done

# 2. Check for "Ghost" Docker containers (orphans from rename)
GHOSTS=$(docker ps -a --filter "name=sparklab-backend" --format "{{.Names}}")
if [ ! -z "$GHOSTS" ]; then
    echo -e "${RED}❌ Found legacy backend containers: $GHOSTS${NC}"
    echo -e "${YELLOW}   These are likely holding port 8000 hostage.${NC}"
    CONFLICTS=$((CONFLICTS+1))
fi

if [ $CONFLICTS -gt 0 ]; then
    echo -e "\n${YELLOW}FIX: Run 'docker compose down --remove-orphans' to clear these blockages.${NC}"
    exit 1
else
    echo -e "\n${GREEN}🚀 All clear! You are ready to start the stack.${NC}"
    exit 0
fi

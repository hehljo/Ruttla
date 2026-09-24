#include "DemoState.h"
void ADemoState::AddPoints(int32 P)
{
    if (!HasAuthority()) return;
    RoundScore += P;
}

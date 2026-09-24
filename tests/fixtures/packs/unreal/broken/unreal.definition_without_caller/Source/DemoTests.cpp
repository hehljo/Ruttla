#include "DemoHealth.h"
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FDemoTest, "Demo.Health", 1)
bool FDemoTest::RunTest(const FString& P)
{
    UDemoHealth* H = NewObject<UDemoHealth>();
    H->ApplyDamage(34.0f);
    return true;
}

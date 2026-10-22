module add1(input a, input b, input cin, output sum, output cout);
  assign sum = a ^ b ^ cin;
  assign cout = (a & b) | (a & cin) | (b & cin);
endmodule

module top_module(input [31:0] a, input [31:0] b, output [31:0] sum);
  wire carry_low;
  add16 lower (.a(a[15:0]), .b(b[15:0]), .cin(1'b0), .sum(sum[15:0]), .cout(carry_low));
  add16 upper (.a(a[31:16]), .b(b[31:16]), .cin(carry_low), .sum(sum[31:16]), .cout());
endmodule
